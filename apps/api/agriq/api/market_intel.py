"""Farm-to-Market Optimizer API (Phase 6 §22).

Additive to the existing ``GET /api/market-prices`` route, which is left exactly
as it was. Every route here is session-authenticated; the user id always comes
from the server session, field/crop-cycle ids are ownership-verified by the
service layer (a foreign id raises ``PermissionError`` → 404, indistinguishable
from a missing resource), and no provider key ever reaches the response.

Endpoints
---------
``GET  /api/v1/market/overview``   prices, trend, volatility, market comparison
``GET  /api/v1/market/forecast``   chronological price forecast (or the refusal)
``GET  /api/v1/market/demand``     demand capability state (honest unavailable)
``GET  /api/v1/market/evidence``   provenance, freshness and quality report
``POST /api/v1/market/crop-options``        crop-choice intelligence
``POST /api/v1/market/sell-hold``          sell/hold decision support
``POST /api/v1/market/logistics``          market comparison with cost completeness

Routes only parse, authorise, call the service and serialise — no market maths
lives in this module.

Farmers may supply their own cost figures (quantity, freight rate or freight total,
input cost, market fee). A blank field stays *unknown* and the net value is withheld
as ``NET_VALUE_INCOMPLETE``; an explicit ``0`` is a real, known zero. AGRIQ never
defaults a cost and never estimates freight, yield or input cost.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging import get_logger
from ..core.security import current_user, require_csrf
from ..domain.market import forecasting
from ..services import market_intelligence

market_bp = Blueprint("market_intel", __name__)
logger = get_logger("api.market_intel")

#: Hard ceilings so a crafted request cannot ask for absurd work.
MAX_QUANTITY_QUINTALS = 1_000_000.0
MAX_RATE_PER_KM_QUINTAL = 1_000.0
MAX_COST_TOTAL = 100_000_000.0
MAX_CROP_OPTIONS = 12


def _require_active_user():
    user = current_user()
    if user is None or not user.is_active:
        raise NotFoundError("Sign in to continue.")
    return user


def _optional_number(payload, key: str, ceiling: float, *, allow_zero: bool = False) -> float | None:
    """Parse an optional numeric field; blank means *unknown*, never zero.

    ``allow_zero`` is set for the farmer-supplied cost components, where an
    explicit ``0`` is a real value — no commission paid, no freight paid — and
    must survive as a *known* cost (§26/§27). It is never defaulted: a missing
    field stays ``None`` so the net value is withheld as ``NET_VALUE_INCOMPLETE``.
    """
    value = payload.get(key)
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{key} must be a number.")
    if number < 0 or (number == 0 and not allow_zero):
        raise ValidationError(
            f"{key} must be zero or greater." if allow_zero else f"{key} must be greater than zero."
        )
    if number > ceiling:
        raise ValidationError(f"{key} is above the accepted maximum.")
    return number


def _optional_bool(payload, key: str) -> bool | None:
    if key not in payload or payload.get(key) is None:
        return None
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    raise ValidationError(f"{key} must be true or false.")


def _int_arg(name: str, default: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValidationError(f"{name} must be an integer.")


def _call(fn, *args, **kwargs):
    """Run a service call, mapping failures to explicit states (§22, §26).

    * a foreign field/crop cycle → 404 (indistinguishable from missing)
    * invalid input → 400
    * any other degradation → an honest ``unavailable`` payload, never a crash
      and never a value that was not retrieved.
    """
    try:
        return fn(*args, **kwargs)
    except PermissionError:
        raise NotFoundError("Field not found for your account.")
    except ValidationError:
        raise
    except Exception as exc:
        logger.warning(
            "market_intel_failed capability=%s error=%s", getattr(fn, "__name__", "unknown"),
            type(exc).__name__,
        )
        return {
            "ok": False,
            "capability": getattr(fn, "__name__", "unknown"),
            "status": "unavailable",
            "message": (
                "Market intelligence is temporarily unavailable. No figures are shown "
                "rather than unverified ones."
            ),
        }


# ---------------------------------------------------------------------------
# Read-only views
# ---------------------------------------------------------------------------

@market_bp.get("/api/v1/market/overview")
def get_overview():
    user = _require_active_user()
    payload = request.args
    quantity = _query_float(payload, "quantity_quintals", MAX_QUANTITY_QUINTALS)
    rate = _query_float(
        payload, "transport_rate_per_km_quintal", MAX_RATE_PER_KM_QUINTAL, allow_zero=True
    )
    freight = _query_float(payload, "transport_cost_total", MAX_COST_TOTAL, allow_zero=True)
    result = _call(
        market_intelligence.overview,
        user.id,
        field_id=_int_arg("field_id"),
        crop_cycle_id=_int_arg("crop_cycle_id"),
        commodity=(payload.get("commodity") or None),
        quantity_quintals=quantity,
        transport_rate_per_km_quintal=rate,
        transport_cost_total=freight,
        include_provider=(payload.get("provider", "1") not in ("0", "false", "no")),
    )
    return jsonify(result)


@market_bp.get("/api/v1/market/forecast")
def get_forecast():
    user = _require_active_user()
    horizon = _int_arg("horizon_days", 7)
    if horizon not in forecasting.SUPPORTED_HORIZONS:
        raise ValidationError(f"horizon_days must be one of {list(forecasting.SUPPORTED_HORIZONS)}.")
    result = _call(
        market_intelligence.forecast_prices,
        user.id,
        field_id=_int_arg("field_id"),
        crop_cycle_id=_int_arg("crop_cycle_id"),
        commodity=(request.args.get("commodity") or None),
        horizon_days=horizon,
        include_provider=(request.args.get("provider", "1") not in ("0", "false", "no")),
    )
    return jsonify(result)


@market_bp.get("/api/v1/market/demand")
def get_demand():
    user = _require_active_user()
    overview = _call(
        market_intelligence.overview,
        user.id,
        field_id=_int_arg("field_id"),
        crop_cycle_id=_int_arg("crop_cycle_id"),
        commodity=(request.args.get("commodity") or None),
        include_provider=False,
    )
    return jsonify({
        "ok": True,
        "capability": "demand",
        "crop": overview.get("crop"),
        "demand": overview.get("demand"),
    })


@market_bp.get("/api/v1/market/evidence")
def get_evidence():
    user = _require_active_user()
    result = _call(
        market_intelligence.evidence_report,
        user.id,
        field_id=_int_arg("field_id"),
        crop_cycle_id=_int_arg("crop_cycle_id"),
        commodity=(request.args.get("commodity") or None),
    )
    return jsonify(result)


# ---------------------------------------------------------------------------
# Decision support (state-changing semantics → CSRF required)
# ---------------------------------------------------------------------------

@market_bp.post("/api/v1/market/crop-options")
@require_csrf
def post_crop_options():
    user = _require_active_user()
    payload = request.get_json(silent=True) or {}
    crops = payload.get("crops")
    if crops is not None:
        if not isinstance(crops, list) or not all(isinstance(item, str) for item in crops):
            raise ValidationError("crops must be a list of crop names.")
        if len(crops) > MAX_CROP_OPTIONS:
            raise ValidationError(f"at most {MAX_CROP_OPTIONS} crops can be evaluated per request.")
    result = _call(
        market_intelligence.crop_options,
        user.id,
        field_id=payload.get("field_id"),
        crop_cycle_id=payload.get("crop_cycle_id"),
        season=(payload.get("season") or None),
        crops=crops,
        include_provider=bool(payload.get("include_market", False)),
    )
    return jsonify(result)


@market_bp.post("/api/v1/market/sell-hold")
@require_csrf
def post_sell_hold():
    user = _require_active_user()
    payload = request.get_json(silent=True) or {}
    horizon = payload.get("horizon_days", 7)
    try:
        horizon = int(horizon)
    except (TypeError, ValueError):
        raise ValidationError("horizon_days must be an integer.")
    if horizon not in forecasting.SUPPORTED_HORIZONS:
        raise ValidationError(f"horizon_days must be one of {list(forecasting.SUPPORTED_HORIZONS)}.")
    result = _call(
        market_intelligence.sell_hold,
        user.id,
        field_id=payload.get("field_id"),
        crop_cycle_id=payload.get("crop_cycle_id"),
        commodity=(payload.get("commodity") or None),
        market=(payload.get("market") or None),
        storage_available=_optional_bool(payload, "storage_available"),
        horizon_days=horizon,
    )
    return jsonify(result)


@market_bp.post("/api/v1/market/logistics")
@require_csrf
def post_logistics():
    user = _require_active_user()
    payload = request.get_json(silent=True) or {}
    result = _call(
        market_intelligence.logistics,
        user.id,
        field_id=payload.get("field_id"),
        crop_cycle_id=payload.get("crop_cycle_id"),
        commodity=(payload.get("commodity") or None),
        quantity_quintals=_optional_number(payload, "quantity_quintals", MAX_QUANTITY_QUINTALS),
        transport_rate_per_km_quintal=_optional_number(
            payload, "transport_rate_per_km_quintal", MAX_RATE_PER_KM_QUINTAL, allow_zero=True
        ),
        transport_cost_total=_optional_number(
            payload, "transport_cost_total", MAX_COST_TOTAL, allow_zero=True
        ),
        input_cost_total=_optional_number(
            payload, "input_cost_total", MAX_COST_TOTAL, allow_zero=True
        ),
        market_fee_total=_optional_number(
            payload, "market_fee_total", MAX_COST_TOTAL, allow_zero=True
        ),
    )
    return jsonify(result)


def _query_float(params, key: str, ceiling: float, *, allow_zero: bool = False) -> float | None:
    """Query-string twin of :func:`_optional_number` (same unknown-vs-zero rule)."""
    value = params.get(key)
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{key} must be a number.")
    if number < 0 or (number == 0 and not allow_zero):
        raise ValidationError(
            f"{key} must be zero or greater and at most {ceiling:g}."
            if allow_zero
            else f"{key} must be greater than zero and at most {ceiling:g}."
        )
    if number > ceiling:
        raise ValidationError(f"{key} must be zero or greater and at most {ceiling:g}.")
    return number


__all__ = ["market_bp"]
