"""Farm-to-Market Optimizer service (Phase 6) — orchestration layer.

Combines the existing pieces into farmer-facing market intelligence:

    Shared Farmer Context (§4)
        + provider records (existing market_service, official AGMARKNET only)
        + persisted history (market_price_records — real rows only)
        + verified weather (existing weather_service)
        + Phase 5 risk assessments (existing risk_repository)
            ↓
    domain/market/* deterministic engines
            ↓
    evidence-carrying payloads (provenance + freshness + missing information)

Boundaries this module respects:

* The LLM is never in this path. Market numbers come from records; explanations
  come later from the copilot, over these structured results.
* Provider failure is never converted into data. It becomes an explicit
  unavailable state with the provider's reason.
* Provider calls are cached for ``MARKET_SNAPSHOT_TTL_SECONDS`` and only made
  where they are actually needed (see :func:`overview`). Crop options never
  fan out into one provider call per candidate crop.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from cachetools import TTLCache

from ..core.logging import get_logger
from ..domain.market import decision, forecasting, normalization, suitability, trend
from ..domain.market.normalization import PRICE_UNIT
from . import farmer_context, market_service

logger = get_logger("services.market_intelligence")

#: One provider result per (commodity, district, state) inside the TTL. Sized and
#: scoped so a dashboard refresh cannot hammer an official endpoint (§25).
_CACHE_KEY = "market_intel_provider_cache"
_CACHE_MAXSIZE = 128
_CACHE_DEFAULT_TTL = 21600
#: Fallback cache for calls made outside an app context (CLI, scripts).
_FALLBACK_CACHE: "Optional[TTLCache]" = None

#: Crops offered for crop-choice analysis when the farmer names none.
DEFAULT_CROP_OPTION_LIMIT = 8


def _ttl_seconds() -> int:
    try:
        from flask import current_app

        return max(60, int(current_app.config.get("MARKET_SNAPSHOT_TTL_SECONDS", _CACHE_DEFAULT_TTL)))
    except Exception:  # pragma: no cover - outside an app context
        return _CACHE_DEFAULT_TTL


def _new_cache(ttl: int) -> "TTLCache[tuple[str, str, str], dict[str, Any]]":
    return TTLCache(maxsize=_CACHE_MAXSIZE, ttl=ttl)


def clear_cache() -> None:
    """Drop cached provider payloads (used by tests and after configuration change)."""
    global _FALLBACK_CACHE
    _FALLBACK_CACHE = None
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            current_app.extensions.pop(_CACHE_KEY, None)
    except Exception:  # pragma: no cover - outside an app context
        return


def _cache() -> "TTLCache[tuple[str, str, str], dict[str, Any]]":
    """The provider cache for the running app and the configured TTL window.

    ``cachetools`` exposes ``ttl`` as a read-only property, so a configuration
    change rebuilds the cache instead of mutating it — that is what honours the
    documented ``MARKET_SNAPSHOT_TTL_SECONDS``. The cache lives on the app so two
    apps in one process (web, CLI, tests) never inherit each other's provider
    state; a cached failure must not outlive the configuration that caused it.
    """
    global _FALLBACK_CACHE
    ttl = _ttl_seconds()
    try:
        from flask import current_app, has_app_context

        in_app = has_app_context()
    except Exception:  # pragma: no cover - outside an app context
        in_app = False
    if not in_app:
        if _FALLBACK_CACHE is None or _FALLBACK_CACHE.ttl != ttl:
            _FALLBACK_CACHE = _new_cache(ttl)
        return _FALLBACK_CACHE
    holder = current_app.extensions.get(_CACHE_KEY)
    if holder is None or holder[0] != ttl:
        holder = (ttl, _new_cache(ttl))
        current_app.extensions[_CACHE_KEY] = holder
    return holder[1]


def _cached_prices(commodity: str, district: str | None, state: str | None) -> dict[str, Any]:
    """Provider fetch with a TTL cache; failures are cached too (bounded retries)."""
    cache = _cache()
    key = (commodity.strip().lower(), (district or "").strip().lower(), (state or "").strip().lower())
    cached = cache.get(key)
    if cached is not None:
        return cached
    result = market_service.get_mandi_prices(commodity=commodity, district=district, state=state or "Odisha")
    cache[key] = result
    return result


def _context(user_id: int, field_id: int | None, crop_cycle_id: int | None) -> dict[str, Any]:
    """Ownership-verified farmer context (raises PermissionError on foreign ids)."""
    return farmer_context.build_farmer_context(
        user_id, field_id=field_id, crop_cycle_id=crop_cycle_id, include_weather=True
    )


def _farm_coordinates(context: Mapping[str, Any]) -> tuple[Optional[float], Optional[float]]:
    field = context.get("field") or {}
    farm = context.get("farm") or {}
    lat = field.get("latitude") if field.get("latitude") is not None else farm.get("latitude")
    lon = field.get("longitude") if field.get("longitude") is not None else farm.get("longitude")
    return lat, lon


def _weather_values(context: Mapping[str, Any]) -> dict[str, Any]:
    """Verified weather inputs for suitability, with explicit availability."""
    weather = context.get("weather") or {}
    if not weather.get("available"):
        return {"available": False, "reason": weather.get("reason", "weather_unavailable")}
    rain = weather.get("rain")
    if rain is None:
        rain = weather.get("precipitation")
    return {
        "available": True,
        "temp": weather.get("temp"),
        "humidity": weather.get("humidity"),
        "rain_mm": rain,
        "freshness": weather.get("freshness"),
        "retrieved_at": weather.get("retrieved_at"),
        "source": weather.get("provider") or "Open-Meteo",
    }


def _risk_rows(user_id: int, field_id: int | None) -> list[dict[str, Any]]:
    """Latest stored Phase 5 assessments for the field (never recomputed here).

    Reading the persisted run keeps Phase 6 cheap and avoids a second provider
    round-trip: if no risk run exists yet, the market payload simply says so.
    """
    if not field_id:
        return []
    from ..repositories.risk_repository import RiskAssessmentRepository

    try:
        rows = RiskAssessmentRepository.active_run_for_field(field_id, user_id)
    except Exception as exc:  # pragma: no cover - database degradation
        logger.warning("risk_rows_unavailable error=%s", type(exc).__name__)
        return []
    import json

    result: list[dict[str, Any]] = []
    for row in rows:
        try:
            reasons = json.loads(row.reasons_json) if row.reasons_json else []
        except (TypeError, ValueError):
            reasons = []
        result.append({
            "risk_type": row.risk_type,
            "status": row.status,
            "threat": row.threat,
            "probability": row.probability,
            "confidence": row.confidence,
            "reasons": reasons,
            "assessment_method": row.assessment_method,
            "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        })
    return result


def _assemble_series(
    context: Mapping[str, Any],
    commodity: str,
    *,
    include_provider: bool,
) -> dict[str, Any]:
    """Normalized official series for a commodity: provider (fresh) + stored history.

    Returns accepted records, the quarantine report and the provider state. The
    provider is optional so read-only views do not fan out into network calls.
    """
    farmer = context.get("farmer") or {}
    district = farmer.get("district")
    state = farmer.get("state") or "Odisha"

    provider_state: dict[str, Any] = {"requested": include_provider, "available": False,
                                      "reason": "not_requested", "retrieved_at": None}
    # The provider filters on its own commodity names, so a catalog key is
    # requested under the catalog display name instead of being sent verbatim.
    provider_commodity = normalization.provider_commodity_name(commodity) or commodity
    fetched_records: list[dict[str, Any]] = []
    if include_provider:
        try:
            result = _cached_prices(provider_commodity, district, state)
        except Exception as exc:  # provider outage: degrade, never substitute data
            logger.warning("market_provider_failed error=%s", type(exc).__name__)
            result = {"available": False, "reason": "provider_request_failed",
                      "records": [], "retrieved_at": None}
        provider_state = {
            "requested": True,
            "available": bool(result.get("available")),
            "reason": result.get("reason"),
            "retrieved_at": result.get("retrieved_at"),
            "provider": result.get("provider"),
            "commodity_requested": provider_commodity,
        }
        if result.get("available"):
            fetched_records = list(result.get("records") or [])

    stored = market_service.stored_history(commodity, district=district, state=state)

    # Provider rows first so they win dedupe ties (newest data), then stored rows.
    normalization_result = normalization.normalize_records(
        list(fetched_records) + list(stored), expected_commodity=commodity
    )
    return {
        "accepted": normalization_result.accepted,
        "quality": normalization_result.quality_summary,
        "quarantined": [item.to_dict() for item in normalization_result.quarantined],
        "provider": provider_state,
        "provider_commodity": provider_commodity,
        "district": district,
        "state": state,
    }


def _scope_note(series: Mapping[str, Any]) -> str:
    """State which location's records the numbers may come from (§6, §7).

    Prices from another district or state are never substituted for the farmer's,
    so a thin local history is reported as thin rather than filled from elsewhere.
    """
    district = series.get("district") or "the farmer's district"
    state = series.get("state") or "the farmer's state"
    return (
        f"Only official records for {district}, {state} are used; no other district's "
        "or state's price series is substituted for it."
    )


def _series_provenance(series: Mapping[str, Any]) -> dict[str, Any]:
    """Freshness provenance describing what the assembled series is built from."""
    from ..domain.market.freshness import provenance, unavailable_provenance

    accepted = series.get("accepted") or []
    if not accepted:
        reason = (
            series.get("provider", {}).get("reason")
            or "no_official_records_for_this_crop_and_district"
        )
        return unavailable_provenance(str(reason))

    newest = max(
        (record for record in accepted if record.arrival_date),
        key=lambda record: record.arrival_date,
        default=None,
    )
    source = accepted[0].source
    return provenance(
        source=source,
        retrieved_at=newest.retrieved_at if newest else None,
        observed_at=newest.arrival_date.isoformat() if newest and newest.arrival_date else None,
        price_date=newest.arrival_date.isoformat() if newest and newest.arrival_date else None,
        record_count=len(accepted),
        detail=(
            f"{len(accepted)} usable official record(s); "
            f"{series.get('quality', {}).get('quarantined', 0)} quarantined by the quality gate"
        ),
    )


# ---------------------------------------------------------------------------
# Public capabilities
# ---------------------------------------------------------------------------

def overview(
    user_id: int,
    *,
    field_id: int | None = None,
    crop_cycle_id: int | None = None,
    commodity: str | None = None,
    quantity_quintals: float | None = None,
    transport_rate_per_km_quintal: float | None = None,
    transport_cost_total: float | None = None,
    input_cost_total: float | None = None,
    market_fee_total: float | None = None,
    include_provider: bool = True,
) -> dict[str, Any]:
    """Prices, trend, volatility, demand state and market comparison (§6, §12)."""
    context = _context(user_id, field_id, crop_cycle_id)
    cycle = context.get("crop_cycle") or {}
    crop = commodity or cycle.get("crop")
    if not crop:
        return _no_crop_payload("overview")

    series = _assemble_series(context, crop, include_provider=include_provider)
    accepted = series["accepted"]
    provenance = _series_provenance(series)

    farmer = context.get("farmer") or {}
    farm_lat, farm_lon = _farm_coordinates(context)
    comparison = decision.compare_markets(
        accepted,
        provider_commodity=series.get("provider_commodity"),
        farmer_district=farmer.get("district"),
        farm_lat=farm_lat,
        farm_lon=farm_lon,
        quantity_quintals=quantity_quintals,
        transport_rate_per_km_quintal=transport_rate_per_km_quintal,
        transport_cost_total=transport_cost_total,
        input_cost_total=input_cost_total,
        market_fee_total=market_fee_total,
    )
    latest = trend.latest_by_market(accepted)

    return {
        "ok": True,
        "capability": "market_overview",
        "crop": crop,
        "crop_name": normalization.crop_display_name(normalization.resolve_commodity(crop)),
        "district": farmer.get("district"),
        "state": farmer.get("state"),
        "price_unit": PRICE_UNIT,
        "provenance": provenance,
        "provider": series["provider"],
        "provider_commodity": series["provider_commodity"],
        "data_quality": series["quality"],
        "quarantined_records": series["quarantined"],
        "latest_prices": [
            {
                "market": record.market,
                "district": record.district,
                "variety": record.variety,
                "modal_price": record.modal_price,
                "min_price": record.min_price,
                "max_price": record.max_price,
                "price_date": record.arrival_date.isoformat() if record.arrival_date else None,
                "source": record.source,
                "retrieved_at": record.retrieved_at,
            }
            for record in latest
        ],
        "trend": trend.trend(accepted),
        "volatility": trend.volatility(accepted),
        "demand": demand_state(series),
        "comparison": comparison,
        "logistics_limitations": comparison["logistics_limitations"],
        "limitations": _overview_limitations(series),
    }


def demand_state(series: Mapping[str, Any]) -> dict[str, Any]:
    """Demand capability state (§9).

    The configured AGMARKNET resource publishes daily provisional **prices**; it
    does not publish arrival quantities. AGRIQ therefore has no legitimate demand
    or arrival-proxy series, and this capability reports that instead of showing a
    percentage nobody could verify.
    """
    return {
        "available": False,
        "reason": "arrivals_not_published_by_configured_source",
        "classification": None,
        "note": (
            "Demand requires real arrival/quantity data. The configured official market "
            "resource does not publish arrivals for these records, so no demand figure, "
            "proxy or percentage is produced."
        ),
        "would_require": (
            "An official arrival-quantity series (for example the AGMARKNET arrivals resource) "
            "with recorded provenance, after which an arrivals-based supply proxy could be "
            "published and clearly labelled as a proxy — never as consumer demand."
        ),
        "records_available": len(series.get("accepted") or []),
    }


def forecast_prices(
    user_id: int,
    *,
    field_id: int | None = None,
    crop_cycle_id: int | None = None,
    commodity: str | None = None,
    horizon_days: int = 7,
    include_provider: bool = True,
) -> dict[str, Any]:
    """Chronological price forecast over real official history (§7, §8)."""
    context = _context(user_id, field_id, crop_cycle_id)
    cycle = context.get("crop_cycle") or {}
    crop = commodity or cycle.get("crop")
    if not crop:
        return _no_crop_payload("price_forecast")

    series = _assemble_series(context, crop, include_provider=include_provider)
    accepted = series["accepted"]
    points = trend.series_points(accepted)
    outcome = forecasting.forecast(points, horizon_days=horizon_days)
    provenance = _series_provenance(series)

    payload: dict[str, Any] = {
        "ok": True,
        "capability": "price_forecast",
        "crop": crop,
        "crop_name": normalization.crop_display_name(normalization.resolve_commodity(crop)),
        "horizon": f"{horizon_days}_days",
        "provenance": provenance,
        "provider_commodity": series["provider_commodity"],
        "data_quality": series["quality"],
        "observations": len(points),
        "series": points,
        "model_version": forecasting.MODEL_VERSION,
        "forecast": outcome.to_dict(),
    }
    if outcome.status != "ok":
        payload["limitations"] = [
            outcome.reason or "insufficient verified history for a forecast",
            _scope_note(series),
            "AGRIQ publishes a forecast only from official records it actually holds; "
            "no number is generated to fill the gap.",
        ]
    else:
        payload["limitations"] = [
            _scope_note(series),
            "Official AGMARKET provisional daily modal prices; not live quotes.",
            "Forecast accuracy metrics are computed on a chronological test block from the "
            "same series and are reported with the candidates they beat (or did not beat).",
        ]
    return payload


def crop_options(
    user_id: int,
    *,
    field_id: int | None = None,
    crop_cycle_id: int | None = None,
    season: str | None = None,
    crops: list[str] | None = None,
    include_provider: bool = False,
) -> dict[str, Any]:
    """Crop-choice intelligence (§5) combining suitability, market and risk facts.

    Provider calls are OFF by default: evaluating many candidate crops must not
    become one official API request per crop. Price context therefore comes from
    stored history, and a crop with no stored history is reported as having no
    verified price context — never given an invented one.
    """
    context = _context(user_id, field_id, crop_cycle_id)
    cycle = context.get("crop_cycle") or {}
    farmer = context.get("farmer") or {}
    district = farmer.get("district") or (context.get("farm") or {}).get("district")
    if not district:
        return {
            "ok": False,
            "capability": "crop_options",
            "status": "insufficient_data",
            "message": "A district is required to judge crop suitability.",
            "options": [],
        }

    season = season or cycle.get("season")
    weather = _weather_values(context)
    risk_rows = _risk_rows(user_id, (context.get("field") or {}).get("id"))

    if crops:
        candidate_keys = [key for key in (normalization.resolve_commodity(crop) for crop in crops) if key]
    else:
        candidate_keys = suitability.candidate_crops(district, season)[:DEFAULT_CROP_OPTION_LIMIT]

    options: list[dict[str, Any]] = []
    for crop_key in candidate_keys:
        series = _assemble_series(context, crop_key, include_provider=include_provider)
        accepted = series["accepted"]
        suitability_result = suitability.evaluate_crop(
            crop_key,
            district=district,
            season=season,
            weather=weather if weather.get("available") else None,
            rain_mm=weather.get("rain_mm") if weather.get("available") else None,
        )
        price_context = _price_context(accepted, crop_key)
        options.append({
            **suitability_result,
            "agronomic": {
                "recommendation_status": suitability_result["recommendation_status"],
                "factors": suitability_result["factors"],
            },
            "market": price_context,
            "provenance": _series_provenance(series),
        })

    ranked = _rank_options(options)
    return {
        "ok": True,
        "capability": "crop_options",
        "district": district,
        "season": season,
        "evaluated_crops": [option["crop"] for option in options],
        "ranking_method": (
            "Agronomic suitability first (from the crop catalog and district profile), then "
            "verified price context. No opaque score is computed and no crop is recommended "
            "without stating why."
        ),
        "options": ranked,
        "market_price_context": (
            "Price context uses official records already stored for this district; "
            "crops without stored records show price_context_available=false."
        ),
        "risk_context": risk_rows,
        "risk_integration_note": (
            "Phase 5 assessments are attached as context. Each risk type is counted once and "
            "only where it logically affects the decision (§14)."
        ),
        "confidence": {
            "status": "not_calibrated",
            "basis": "Rule-based assessment over curated catalogs and verified records.",
        },
    }


def _price_context(records: list[normalization.NormalizedRecord], crop_key: str) -> dict[str, Any]:
    if not records:
        return {
            "price_context_available": False,
            "reason": "no_official_records_stored_for_this_crop_and_district",
            "latest_modal_price": None,
            "price_unit": PRICE_UNIT,
        }
    latest = trend.latest_by_market(records)
    prices = [record.modal_price for record in latest if record.modal_price is not None]
    return {
        "price_context_available": bool(prices),
        "latest_modal_price": round(sum(prices) / len(prices), 2) if prices else None,
        "latest_price_note": (
            "Mean of the newest official record per market; individual market prices are in the "
            "market overview." if prices else None
        ),
        "markets_reporting": len(prices),
        "price_unit": PRICE_UNIT,
        "volatility": trend.volatility(records),
        "price_date": max(
            (record.arrival_date.isoformat() for record in latest if record.arrival_date),
            default=None,
        ),
    }


def _rank_options(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order options by documented, inspectable criteria (no hidden score)."""
    status_rank = {"suitable": 0, "marginal": 1, "insufficient_data": 2, "unsuitable": 3}

    def sort_key(option: Mapping[str, Any]) -> tuple[int, float]:
        market = option.get("market") or {}
        price = market.get("latest_modal_price")
        return (
            status_rank.get(str(option.get("recommendation_status")), 4),
            -(price if isinstance(price, (int, float)) else 0.0),
        )

    ranked = sorted(options, key=sort_key)
    for position, option in enumerate(ranked, start=1):
        option["rank"] = position
    return ranked


def sell_hold(
    user_id: int,
    *,
    field_id: int | None = None,
    crop_cycle_id: int | None = None,
    commodity: str | None = None,
    market: str | None = None,
    storage_available: bool | None = None,
    horizon_days: int = 7,
) -> dict[str, Any]:
    """Sell/hold decision support over verified evidence (§10, §14)."""
    context = _context(user_id, field_id, crop_cycle_id)
    cycle = context.get("crop_cycle") or {}
    crop = commodity or cycle.get("crop")
    if not crop:
        return _no_crop_payload("sell_hold")

    series = _assemble_series(context, crop, include_provider=True)
    accepted = series["accepted"]
    crop_key = normalization.resolve_commodity(crop)
    scoped = [r for r in accepted if not market or r.market.strip().lower() == market.strip().lower()]

    latest = trend.latest_by_market(scoped or accepted)
    current_price = latest[0].modal_price if latest else None
    price_market = latest[0].market if latest else None

    forecast_payload = forecasting.forecast(trend.series_points(scoped or accepted),
                                           horizon_days=horizon_days).to_dict()
    field_id_value = (context.get("field") or {}).get("id")
    risk_rows = _risk_rows(user_id, field_id_value)

    result = decision.sell_hold(
        crop_key=crop_key,
        current_price=current_price,
        trend=trend.trend(scoped or accepted),
        volatility=trend.volatility(scoped or accepted),
        forecast=forecast_payload,
        storage_available=storage_available,
        risk_rows=risk_rows,
    )
    return {
        "ok": True,
        "capability": "sell_hold",
        "crop": crop,
        "crop_name": normalization.crop_display_name(crop_key),
        "field_id": field_id_value,
        "market": price_market,
        "requested_market": market,
        "price_unit": PRICE_UNIT,
        "provenance": _series_provenance(series),
        "provider_commodity": series["provider_commodity"],
        "data_quality": series["quality"],
        "current_price": current_price,
        **result,
        "risk_integration": {
            "risk_types_considered": [row["risk_type"] for row in risk_rows],
            "note": (
                "Each Phase 5 risk type enters the decision at most once; production-side risks "
                "(heat, water, disease) are reported as context because they affect expected "
                "volume rather than sell timing."
            ),
        },
    }


def logistics(
    user_id: int,
    *,
    field_id: int | None = None,
    crop_cycle_id: int | None = None,
    commodity: str | None = None,
    quantity_quintals: float | None = None,
    transport_rate_per_km_quintal: float | None = None,
    transport_cost_total: float | None = None,
    input_cost_total: float | None = None,
    market_fee_total: float | None = None,
) -> dict[str, Any]:
    """Market comparison with distance proxies and honest cost completeness (§11–13)."""
    return overview(
        user_id,
        field_id=field_id,
        crop_cycle_id=crop_cycle_id,
        commodity=commodity,
        quantity_quintals=quantity_quintals,
        transport_rate_per_km_quintal=transport_rate_per_km_quintal,
        transport_cost_total=transport_cost_total,
        input_cost_total=input_cost_total,
        market_fee_total=market_fee_total,
        include_provider=True,
    )


def evidence_report(
    user_id: int,
    *,
    field_id: int | None = None,
    crop_cycle_id: int | None = None,
    commodity: str | None = None,
) -> dict[str, Any]:
    """Provenance, freshness and data-quality report for market intelligence (§17)."""
    context = _context(user_id, field_id, crop_cycle_id)
    cycle = context.get("crop_cycle") or {}
    crop = commodity or cycle.get("crop")
    if not crop:
        return _no_crop_payload("evidence")

    series = _assemble_series(context, crop, include_provider=True)
    return {
        "ok": True,
        "capability": "market_evidence",
        "crop": crop,
        "crop_name": normalization.crop_display_name(normalization.resolve_commodity(crop)),
        "provenance": _series_provenance(series),
        "provider": series["provider"],
        "provider_commodity": series["provider_commodity"],
        "data_quality": series["quality"],
        "quarantined_records": series["quarantined"],
        "sources": MARKET_SOURCES,
        "freshness_policy": FRESHNESS_POLICY,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _no_crop_payload(capability: str) -> dict[str, Any]:
    return {
        "ok": False,
        "capability": capability,
        "status": "insufficient_data",
        "message": (
            "Register a crop cycle (or pass a commodity) before market intelligence can run: "
            "AGRIQ does not guess which crop a farmer means."
        ),
    }


def _overview_limitations(series: Mapping[str, Any]) -> list[str]:
    notes = [
        "Official AGMARKNET provisional daily prices, not live quotes.",
        "Varieties are never mixed: comparisons group by commodity and variety.",
    ]
    quality = series.get("quality") or {}
    if quality.get("quarantined"):
        notes.append(
            f"{quality['quarantined']} provider record(s) were quarantined by the data-quality "
            "gate and excluded from every calculation."
        )
    if not series.get("accepted"):
        notes.append(
            "No usable official records were available for this crop and district; every price "
            "field is therefore empty rather than estimated."
        )
    return notes


#: Documented data sources (mirrored in docs/market-data-sources.md).
MARKET_SOURCES: list[dict[str, Any]] = [
    {
        "name": "AGMARKNET daily mandi prices",
        "provider": "Directorate of Marketing & Inspection via data.gov.in (OGD Platform)",
        "resource_id": "9ef84268-d588-465a-a308-a864a43d0070",
        "url": "https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070",
        "coverage": "India; AGRIQ queries the farmer's district and state",
        "variables": "state, district, market, commodity, variety, arrival_date, min/max/modal price",
        "unit": PRICE_UNIT,
        "update_frequency": "Daily provisional reports published by mandis",
        "access": "Server-side provider key held by AGRIQ; never exposed to the browser",
        "limitations": (
            "Provisional and self-reported by markets; no arrival quantities in this resource; "
            "market names carry no coordinates."
        ),
    },
    {
        "name": "AGRIQ persisted market record history",
        "provider": "AGRIQ (rows returned by the source above and stored unmodified)",
        "url": None,
        "coverage": "Rows actually fetched over this deployment's lifetime",
        "variables": "As returned by AGMARKNET, plus source, retrieval time and record hash",
        "unit": PRICE_UNIT,
        "update_frequency": "On demand (dashboard, copilot) with a documented TTL cache",
        "access": "Internal",
        "limitations": (
            "History depth equals how long this deployment has been collecting; it is never "
            "backfilled, so trend and forecast features report insufficiency until it grows."
        ),
    },
]

#: Freshness policy mirrored from domain.risk_engine.freshness (single source).
FRESHNESS_POLICY: dict[str, Any] = {
    "classifier": "domain.risk_engine.freshness.classify (input kind 'market')",
    "fresh_max_hours": 24,
    "aging_max_hours": 72,
    "stale_max_hours": 240,
    "beyond": "expired",
    "no_timestamp": "unavailable",
    "note": (
        "AGMARKNET publishes provisional daily prices; a record is never described as live. "
        "Freshness multiplies confidence, and stale data is labelled rather than hidden."
    ),
}


__all__ = [
    "overview",
    "forecast_prices",
    "crop_options",
    "sell_hold",
    "logistics",
    "evidence_report",
    "demand_state",
    "clear_cache",
    "MARKET_SOURCES",
    "FRESHNESS_POLICY",
]
