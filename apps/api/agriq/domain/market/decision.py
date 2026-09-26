"""Economics, sell/hold and market comparison (Phase 6 §10–13).

Two rules dominate this module:

1. **Missing costs are never invented.** A net value is published only when the
   quantity and every cost component are known. With a cost component missing the
   result is ``NET_VALUE_INCOMPLETE`` and names the missing component — a gross
   value is never relabelled as a net value or as "profit".
2. **Insufficient evidence produces no recommendation.** The sell/hold engine
   returns ``INSUFFICIENT_DATA`` unless a verified price is joined by at least one
   observed market or risk fact (trend, forecast, volatility, storage or a Phase 5
   risk). Crop-catalog attributes such as storage class modify a decision; they
   cannot create one. It never forces an answer.

Distance deserves its own caveat: AGMARKNET publishes market *names*, not
coordinates, so a market's distance to the farm is **not** knowable from the
data we hold. What is computable is the straight-line distance from the farm to
the *district centre* of the market's district — a real, documented lower-bound
proxy for out-of-district markets, and unavailable for markets inside the
farmer's own district where it would carry no information. Nothing here is ever
presented as road distance or travel time.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping, Optional, Sequence

from ..catalogs.crops import resolve_crop
from ..catalogs.districts import DISTRICTS, profile_for
from .normalization import PRICE_UNIT, NormalizedRecord

#: Earth radius used for the great-circle distance (km), WGS-84 mean radius.
EARTH_RADIUS_KM = 6371.0088

#: Documented decision tokens (§10).
SELL_NOW = "SELL_NOW"
WAIT = "WAIT"
MONITOR = "MONITOR"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

#: Percentage deadband for using a trend or forecast as evidence.
DIRECTIONAL_DEADBAND_PCT = 2.0

#: Crop categories whose produce is perishable, from the crop catalog.
PERISHABLE_CATEGORIES = ("vegetable", "fruit")


# ---------------------------------------------------------------------------
# Distance
# ---------------------------------------------------------------------------

def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle (straight-line) distance in km."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return round(2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a)), 1)


DISTANCE_BASIS = (
    "Straight-line distance from the field to the district centre of the market's "
    "district. AGMARKNET publishes market names without coordinates, so this is a "
    "lower-bound proxy — NOT road distance and NOT travel time."
)


def market_distance_proxy(
    farm_lat: float | None,
    farm_lon: float | None,
    farmer_district: str | None,
    market_district: str | None,
) -> dict[str, Any]:
    """Distance proxy for a market, or an explicit reason it cannot be computed."""
    if farm_lat is None or farm_lon is None:
        return {"distance_km": None, "distance_basis": DISTANCE_BASIS,
                "reason": "farm_coordinates_unavailable"}
    if not market_district:
        return {"distance_km": None, "distance_basis": DISTANCE_BASIS,
                "reason": "market_district_unavailable"}
    if farmer_district and market_district.strip().lower() == farmer_district.strip().lower():
        return {
            "distance_km": None,
            "distance_basis": DISTANCE_BASIS,
            "reason": (
                "market is inside the farmer's own district; the district-centre proxy "
                "would carry no information about this specific market"
            ),
        }
    centroid = DISTRICTS.get(market_district.strip())
    if centroid is None:
        return {"distance_km": None, "distance_basis": DISTANCE_BASIS,
                "reason": "market_district_not_in_reference_geodata"}
    return {
        "distance_km": great_circle_km(farm_lat, farm_lon, centroid[0], centroid[1]),
        "distance_basis": DISTANCE_BASIS,
        "reason": None,
    }


# ---------------------------------------------------------------------------
# Economics
# ---------------------------------------------------------------------------

def economics(
    *,
    modal_price: float | None,
    quantity_quintals: float | None,
    input_cost_total: float | None = None,
    transport_cost_total: float | None = None,
    market_fee_total: float | None = None,
    price_unit: str = PRICE_UNIT,
) -> dict[str, Any]:
    """Gross value and — only when every component is known — an estimated net.

    Returns ``status="incomplete"`` with ``missing`` naming what is absent
    whenever a component cannot be established. No component is estimated.
    """
    if modal_price is None:
        return {
            "status": "insufficient_data",
            "reason": "no verified modal price for this market",
            "price_unit": price_unit,
        }
    if quantity_quintals is None or quantity_quintals <= 0:
        return {
            "status": "insufficient_data",
            "reason": (
                "sale quantity is required: AGRIQ does not estimate yield, so quantity "
                "must come from the farmer"
            ),
            "price_unit": price_unit,
        }

    gross = round(modal_price * quantity_quintals, 2)
    components = {
        "input_cost_total": input_cost_total,
        "transport_cost_total": transport_cost_total,
        "market_fee_total": market_fee_total,
    }
    missing = [name for name, value in components.items() if value is None]
    known = {name: round(float(value), 2) for name, value in components.items() if value is not None}
    known_total = round(sum(known.values()), 2)

    result: dict[str, Any] = {
        "status": "complete" if not missing else "incomplete",
        "label": "estimated_net_value" if not missing else "NET_VALUE_INCOMPLETE",
        "price_unit": price_unit,
        "quantity_quintals": quantity_quintals,
        "modal_price": modal_price,
        "gross_value": gross,
        "known_costs": known,
        "known_cost_total": known_total,
        "missing_costs": missing,
        "estimated_net_value": round(gross - known_total, 2) if not missing else None,
        "cost_provenance": (
            "All cost components supplied by the farmer; AGRIQ has no verified input-cost "
            "or freight source and therefore never estimates these figures."
        ),
    }
    if missing:
        result["note"] = (
            "A net value is withheld because "
            + ", ".join(missing)
            + " is unknown. AGRIQ does not estimate cost components."
        )
    return result


# ---------------------------------------------------------------------------
# Sell / hold
# ---------------------------------------------------------------------------

def _perishable(crop_key: str | None) -> Optional[bool]:
    if not crop_key:
        return None
    record, _ = resolve_crop(crop_key)
    category = str(record.get("category", "")).lower()
    if not category:
        return None
    return category in PERISHABLE_CATEGORIES


def sell_hold(
    *,
    crop_key: str | None,
    current_price: float | None,
    trend: Mapping[str, Any] | None,
    volatility: Mapping[str, Any] | None,
    forecast: Mapping[str, Any] | None = None,
    storage_available: bool | None = None,
    risk_rows: Sequence[Mapping[str, Any]] = (),
    price_unit: str = PRICE_UNIT,
) -> dict[str, Any]:
    """Transparent sell/hold decision support.

    Each evidence point is one documented fact about the verified data. The
    decision is the weighted direction of the evidence, and every input that is
    missing is listed rather than assumed.
    """
    evidence: list[dict[str, Any]] = []
    missing: list[str] = []
    risks: list[dict[str, Any]] = []

    if current_price is None:
        return {
            "decision": INSUFFICIENT_DATA,
            "reason": "no verified official price is available for this crop and market",
            "evidence": evidence,
            "missing_information": ["verified modal price"],
            "risks": [],
            "confidence": _confidence_block(evidence, ["verified modal price"]),
            "price_unit": price_unit,
        }
    evidence.append({
        "kind": "price",
        "observation": f"Latest official modal price is {current_price} ₹/quintal.",
        "direction": "neutral",
        "weight": 1.0,
    })

    # Trend ------------------------------------------------------------------
    if trend and trend.get("status") == "ok":
        change = trend.get("change_percent")
        direction = trend.get("direction")
        if change is not None:
            if direction == "rising" and change >= DIRECTIONAL_DEADBAND_PCT:
                evidence.append({
                    "kind": "trend",
                    "observation": f"Official records rose {change}% across {trend.get('points')} observation dates.",
                    "direction": "hold",
                    "weight": 1.0,
                })
            elif direction == "falling" and change <= -DIRECTIONAL_DEADBAND_PCT:
                evidence.append({
                    "kind": "trend",
                    "observation": f"Official records fell {change}% across {trend.get('points')} observation dates.",
                    "direction": "sell",
                    "weight": 1.0,
                })
            else:
                evidence.append({
                    "kind": "trend",
                    "observation": f"Official records moved {change}%, inside the ±{DIRECTIONAL_DEADBAND_PCT}% stable band.",
                    "direction": "neutral",
                    "weight": 0.5,
                })
    else:
        missing.append("price trend (needs at least 3 observation dates)")

    # Volatility -------------------------------------------------------------
    if volatility and volatility.get("status") == "ok":
        band = volatility.get("band")
        if band == "high":
            evidence.append({
                "kind": "volatility",
                "observation": (
                    f"Modal prices swing {volatility.get('swing_percent')}% around the median "
                    "(high-volatility band)."
                ),
                "direction": "monitor",
                "weight": 0.5,
            })
        else:
            evidence.append({
                "kind": "volatility",
                "observation": f"Price spread is in the {band}-volatility band.",
                "direction": "neutral",
                "weight": 0.5,
            })
    else:
        missing.append("price volatility (needs at least 2 usable records)")

    # Forecast ---------------------------------------------------------------
    if forecast and forecast.get("status") == "ok" and forecast.get("forecast"):
        first = forecast["forecast"][0].get("modal_price")
        if first is not None and current_price:
            delta_pct = round((first - current_price) / current_price * 100.0, 2)
            if delta_pct >= DIRECTIONAL_DEADBAND_PCT:
                evidence.append({
                    "kind": "forecast",
                    "observation": (
                        f"The {forecast.get('selected_model')} model projects {first} ₹/quintal "
                        f"({delta_pct}% vs the latest official price)."
                    ),
                    "direction": "hold",
                    "weight": 1.0,
                })
            elif delta_pct <= -DIRECTIONAL_DEADBAND_PCT:
                evidence.append({
                    "kind": "forecast",
                    "observation": (
                        f"The {forecast.get('selected_model')} model projects {first} ₹/quintal "
                        f"({delta_pct}% vs the latest official price)."
                    ),
                    "direction": "sell",
                    "weight": 1.0,
                })
            else:
                evidence.append({
                    "kind": "forecast",
                    "observation": f"The model projects {delta_pct}% change — inside the stable band.",
                    "direction": "neutral",
                    "weight": 0.5,
                })
    else:
        reason = (forecast or {}).get("reason") if forecast else None
        missing.append(
            "validated price forecast"
            + (f" ({reason})" if reason else " (insufficient official history)")
        )

    # Perishability + storage ------------------------------------------------
    perishable = _perishable(crop_key)
    if perishable is True:
        evidence.append({
            "kind": "perishability",
            "observation": "The crop catalog classifies this produce as perishable (vegetable/fruit).",
            "direction": "sell",
            "weight": 1.0,
        })
    elif perishable is False:
        evidence.append({
            "kind": "perishability",
            "observation": "The crop catalog classifies this produce as storable (not vegetable/fruit).",
            "direction": "hold",
            "weight": 0.5,
        })
    else:
        missing.append("perishability (crop category unknown)")

    if storage_available is True:
        evidence.append({
            "kind": "storage",
            "observation": "The farmer reports storage is available.",
            "direction": "hold",
            "weight": 0.5,
        })
    elif storage_available is False:
        evidence.append({
            "kind": "storage",
            "observation": "The farmer reports no storage is available.",
            "direction": "sell",
            "weight": 0.5,
        })
    else:
        missing.append("storage availability (farmer-reported)")

    # Risk (Phase 5) — each risk type contributes at most once -----------------
    seen_risk_types: set[str] = set()
    for row in risk_rows:
        risk_type = str(row.get("risk_type") or "")
        if not risk_type or risk_type in seen_risk_types:
            continue
        if str(row.get("status") or "") not in ("elevated", "high", "critical"):
            continue
        seen_risk_types.add(risk_type)
        effect = _risk_effect(risk_type)
        risks.append({
            "risk_type": risk_type,
            "status": row.get("status"),
            "threat": row.get("threat"),
            "effect_on_market_decision": effect,
        })
        if effect == "sell":
            evidence.append({
                "kind": f"risk:{risk_type}",
                "observation": f"{risk_type.replace('_', ' ')} risk is {row.get('status')}.",
                "direction": "sell",
                "weight": 1.0,
            })
        elif effect == "monitor":
            evidence.append({
                "kind": f"risk:{risk_type}",
                "observation": f"{risk_type.replace('_', ' ')} risk is {row.get('status')}.",
                "direction": "monitor",
                "weight": 0.5,
            })

    # Decision ---------------------------------------------------------------
    sell_weight = sum(e["weight"] for e in evidence if e["direction"] == "sell")
    hold_weight = sum(e["weight"] for e in evidence if e["direction"] == "hold")
    monitor_weight = sum(e["weight"] for e in evidence if e["direction"] == "monitor")

    # Crop-catalog attributes describe the produce; only an observed market or risk
    # fact can support a timing view. Without one, the honest answer is that AGRIQ
    # cannot say — a storable crop on a single price is not a reason to hold.
    market_or_risk_facts = [
        e for e in evidence
        if e["kind"] in ("trend", "forecast", "volatility", "storage")
        or e["kind"].startswith("risk:")
    ]
    if not market_or_risk_facts:
        return {
            "decision": INSUFFICIENT_DATA,
            "reason": (
                "only the current official price and the crop's storage class are available; "
                "at least one observed market or risk fact (trend, forecast, volatility, "
                "storage or Phase 5 risk) is required before a timing view is offered"
            ),
            "evidence": evidence,
            "missing_information": missing,
            "risks": risks,
            "confidence": _confidence_block(evidence, missing),
            "price_unit": price_unit,
        }

    if sell_weight > hold_weight and sell_weight >= monitor_weight:
        decision = SELL_NOW
    elif hold_weight > sell_weight and hold_weight >= monitor_weight:
        decision = WAIT
    elif monitor_weight > 0 and monitor_weight >= max(sell_weight, hold_weight):
        decision = MONITOR
    else:
        decision = MONITOR

    return {
        "decision": decision,
        "decision_basis": (
            f"Weighted evidence: sell {sell_weight:g}, hold {hold_weight:g}, monitor {monitor_weight:g}. "
            "Each evidence point is one verified fact; no hidden score is used."
        ),
        "evidence": evidence,
        "risks": risks,
        "missing_information": missing,
        "assumptions": [
            "Prices are official AGMARKNET provisional daily modal prices, not live quotes.",
            "This is decision support, not a price prediction or financial advice.",
            "The model's forecast is published only where official history supports it.",
        ],
        "confidence": _confidence_block(evidence, missing),
        "price_unit": price_unit,
        "requires_expert_confirmation": decision in (SELL_NOW, WAIT),
    }


def _confidence_block(evidence: Sequence[Mapping[str, Any]],
                      missing: Sequence[str]) -> dict[str, Any]:
    """The app's one confidence statement: transparent rules, never calibrated.

    Returned on every sell/hold outcome — including the refusals — so the panel
    never has to render a bare "confidence unavailable" for a rule assessment.
    """
    return {
        "status": "not_calibrated",
        "basis": (
            "The recommendation is a transparent rule assessment over verified inputs. "
            "It has not been statistically calibrated and no percentage is claimed."
        ),
        "evidence_points": len(evidence),
        "missing_inputs": len(missing),
    }


def _risk_effect(risk_type: str) -> Optional[str]:
    """Documented, single-counted mapping from a Phase 5 risk to a timing effect."""
    return {
        # Rain disrupts transport and can damage produce in the field.
        "heavy_rain_flooding": "sell",
        # Volatile prices favour splitting sales / watching rather than waiting blind.
        "market_volatility": "monitor",
        # Production-side risks are reported as context but not re-counted as
        # timing evidence — they affect expected volume, not the sell/hold call.
        "heat_stress": None,
        "water_stress": None,
        "disease_conducive_weather": None,
    }.get(risk_type)


# ---------------------------------------------------------------------------
# Market comparison
# ---------------------------------------------------------------------------

#: The only two admissible transport-cost bases (§26). Freight is never invented.
TRANSPORT_BASIS_FARMER_TOTAL = (
    "Total freight the farmer pays for the trip, supplied by the farmer. The same figure is "
    "applied to every market compared, so it is not a per-market quote."
)
TRANSPORT_BASIS_RATE = (
    "Farmer-supplied rate applied to the straight-line distance proxy; not a quoted freight rate."
)


def _transport_cost(
    *,
    supplied_total: float | None,
    rate_per_km_quintal: float | None,
    distance_km: float | None,
    quantity_quintals: float | None,
) -> tuple[float | None, str | None]:
    """Transport cost (or ``None``) together with the basis that produced it.

    The farmer's own freight total wins over the derived figure: they are the only
    party who knows their freight bill, and the distance available here is a
    straight-line proxy. With neither supplied the cost stays unknown.
    """
    if supplied_total is not None:
        return round(float(supplied_total), 2), TRANSPORT_BASIS_FARMER_TOTAL
    if rate_per_km_quintal is not None and distance_km is not None and quantity_quintals:
        return round(rate_per_km_quintal * distance_km * quantity_quintals, 2), TRANSPORT_BASIS_RATE
    return None, None


def compare_markets(
    records: Sequence[NormalizedRecord],
    *,
    provider_commodity: str | None = None,
    farmer_district: str | None,
    farm_lat: float | None,
    farm_lon: float | None,
    quantity_quintals: float | None = None,
    transport_rate_per_km_quintal: float | None = None,
    transport_cost_total: float | None = None,
    input_cost_total: float | None = None,
    market_fee_total: float | None = None,
) -> dict[str, Any]:
    """Per-variety market comparison with an explicit logistics limitation.

    Gross value is always computed when a quantity is known. Transport cost comes
    from the farmer — either their total freight bill or a ₹/quintal/km rate applied
    to a straight-line distance proxy — and the net stays ``NET_VALUE_INCOMPLETE``
    when neither is supplied. No component is ever estimated here.

    When ``provider_commodity`` is given the comparison covers only that provider
    spelling, so two definitions of the same catalog crop ("Rice" vs
    "Paddy(Dhan)(Common)") are never placed side by side as if comparable.
    """
    from .trend import latest_by_market, scoped, series_points

    if provider_commodity:
        requested = [r for r in records
                     if (r.commodity or "").strip().lower() == provider_commodity.strip().lower()]
        if requested:
            records = requested
    records, scope = scoped(records)

    grouped: dict[tuple[str, str], list[NormalizedRecord]] = {}
    for record in records:
        grouped.setdefault(record.group_key, []).append(record)

    groups: list[dict[str, Any]] = []
    for (commodity_key, variety), group_records in sorted(grouped.items()):
        rows: list[dict[str, Any]] = []
        for record in latest_by_market(group_records):
            distance = market_distance_proxy(
                farm_lat, farm_lon, farmer_district, record.district
            )
            transport_cost, transport_basis = _transport_cost(
                supplied_total=transport_cost_total,
                rate_per_km_quintal=transport_rate_per_km_quintal,
                distance_km=distance["distance_km"],
                quantity_quintals=quantity_quintals,
            )
            econ = economics(
                modal_price=record.modal_price,
                quantity_quintals=quantity_quintals,
                input_cost_total=input_cost_total,
                transport_cost_total=transport_cost,
                market_fee_total=market_fee_total,
            )
            rows.append({
                "market": record.market,
                "district": record.district,
                "variety": record.variety,
                "modal_price": record.modal_price,
                "price_unit": record.price_unit,
                "price_date": record.arrival_date.isoformat() if record.arrival_date else None,
                "retrieved_at": record.retrieved_at,
                "source": record.source,
                "distance_km": distance["distance_km"],
                "distance_basis": distance["distance_basis"],
                "distance_unavailable_reason": distance["reason"],
                "estimated_transport_cost": transport_cost,
                "transport_cost_basis": transport_basis,
                "economics": econ,
                "data_freshness": {
                    "source": record.source,
                    "observed_at": record.arrival_date.isoformat() if record.arrival_date else None,
                    "retrieved_at": record.retrieved_at,
                },
            })

        rows.sort(key=lambda row: (-(row["modal_price"] or 0.0), row["market"]))
        prices = [r["modal_price"] for r in rows if r["modal_price"] is not None]
        top = rows[0] if rows else None
        groups.append({
            "commodity": commodity_key,
            "variety": variety or None,
            "markets": rows,
            "market_count": len(rows),
            "highest_price_market": top["market"] if top else None,
            "price_spread": round(max(prices) - min(prices), 2) if len(prices) >= 2 else None,
            "series_points": len(series_points(group_records)),
            "comparison_note": (
                "Markets are compared within the same commodity and variety only; varieties, "
                "units and districts are never mixed."
            ),
        })

    return {
        "status": "ok" if groups else "insufficient_data",
        "reason": None if groups else "no usable official market records",
        "farmer_district": farmer_district,
        "provider_commodity": scope["provider_commodity"],
        "excluded_provider_commodities": scope["excluded_provider_commodities"],
        "groups": groups,
        "logistics_limitations": [
            DISTANCE_BASIS,
            "Travel time is not published by AGMARKNET and no verified routing source is "
            "configured, so no travel time is shown.",
            "Freight rates are not available from any verified source; a net value is published "
            "only when the farmer supplies the rate, and it is labelled as an estimate.",
        ],
        "gross_vs_net": (
            "gross_value is price × quantity. estimated_net_value is published only when every "
            "cost component is known; otherwise the row reports NET_VALUE_INCOMPLETE."
        ),
    }


def perishability_note(crop_key: str | None) -> dict[str, Any]:
    """Crop-catalog perishability statement (no external claim)."""
    perishable = _perishable(crop_key)
    record, _ = resolve_crop(crop_key)
    return {
        "crop": crop_key,
        "category": record.get("category"),
        "perishable": perishable,
        "basis": "AGRIQ crop catalog category (vegetable/fruit treated as perishable).",
    }


def district_profile(district: str) -> Mapping[str, str]:
    """Expose the curated profile used by suitability for evidence blocks."""
    return profile_for(district)


def unavailable_reason_codes() -> Iterable[str]:
    """Reason codes this module can emit, for documentation/tests."""
    return (
        "farm_coordinates_unavailable",
        "market_district_unavailable",
        "market_district_not_in_reference_geodata",
    )


__all__ = [
    "SELL_NOW",
    "WAIT",
    "MONITOR",
    "INSUFFICIENT_DATA",
    "DISTANCE_BASIS",
    "DIRECTIONAL_DEADBAND_PCT",
    "great_circle_km",
    "market_distance_proxy",
    "economics",
    "sell_hold",
    "compare_markets",
    "perishability_note",
]
