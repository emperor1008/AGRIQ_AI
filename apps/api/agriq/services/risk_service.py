"""Crop Risk Intelligence service (Phase 5) — orchestration layer.

Consumes the Shared Farmer Context (single source of truth §5), the existing
weather service (live + snapshot) and the existing market service (official
AGMARKNET records only), validates freshness, then runs the deterministic
rule analyzers. The LLM is never in this path — risk values come from code,
never from a model (§18).

Persistence is append-only with idempotent dedup (§29, §36): re-analysing a
field inside the assessment TTL returns the existing active assessment rather
than creating duplicates; a changed result supersedes the old record without
destroying history.
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Optional

from ..core.time import utc_now
from ..domain.risk_engine import analyzers, weather_input
from ..domain.risk_engine.base import Assessment, RISK_TYPES
from ..domain.risk_engine import thresholds
from ..domain.risk_engine.freshness import classify
from ..repositories.copilot_repository import RecommendationRepository
from ..repositories.risk_repository import RiskAssessmentRepository
from . import farmer_context, market_service, weather_service

RISK_ASSESSMENT_TTL_MINUTES = 30  # §36: avoid recomputing needlessly

# Market-volatility inputs: commodity ↔ crop mapping (real records only).
_MARKET_COMMODITY = {"rice": "Rice", "tomato": "Tomato"}


def _loads(text: Optional[str]) -> Any:
    if not text:
        return None
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _ttl_minutes() -> int:
    """Idempotency window; env-configurable, default 30 minutes."""
    try:
        from flask import current_app

        return max(1, int(current_app.config.get("RISK_ASSESSMENT_TTL_MINUTES", 30)))
    except Exception:
        return RISK_ASSESSMENT_TTL_MINUTES


def analyze_field(
    user_id: int,
    field_id: int,
    *,
    farm_id: Optional[int] = None,
    crop_cycle_id: Optional[int] = None,
    include_market: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Run all five analyzers for one owned field and persist the results.

    Ownership is enforced by ``build_farmer_context`` (raises PermissionError
    for a foreign field). Returns the farmer-facing payload.
    """
    # 1. Shared Farmer Context — single source of truth (§5). Also proves
    #    ownership of farm/field/crop_cycle before any calculation (§30).
    context = farmer_context.build_farmer_context(
        user_id, farm_id=farm_id, field_id=field_id, crop_cycle_id=crop_cycle_id
    )
    return analyze_context(
        user_id,
        context,
        include_market=include_market,
        force=force,
    )


def analyze_context(
    user_id: int,
    context: Mapping[str, Any],
    *,
    include_market: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Run the risk engine over an already-built farmer context.

    Separate from ``analyze_field`` so the Copilot can pass a context it has
    already loaded without re-fetching (§36 deduplication).
    """
    import time as _time

    started = perf = _time.perf_counter()

    field = context.get("field") or {}
    cycle = context.get("crop_cycle") or {}
    field_id = field.get("id")
    if not field_id:
        return {
            "ok": False,
            "status": "insufficient_data",
            "message": "Register a field with a crop cycle to analyse risk.",
            "assessments": [],
        }

    # 2. Idempotency window (§36): a recent complete run is reused verbatim.
    if not force:
        cached = RiskAssessmentRepository.recent_complete_run(field_id, _ttl_minutes())
        if cached:
            return _run_payload(field_id, context, cached, cached_run=True, duration_ms=0)

    # 3. Verified inputs -------------------------------------------------
    weather_raw = context.get("weather")
    weather = weather_input.gather(weather_raw)

    # Market: only real official records, only when explicitly requested (§14).
    market_ctx: dict[str, Any] = {"available": False, "reason": "not_requested"}
    commodity = _MARKET_COMMODITY.get(str(cycle.get("crop") or "").strip().lower())
    if include_market:
        market_ctx = _load_market_context(context, commodity)

    # 4. Crop-stage from the EXISTING calculation (§23) --------------------
    stage = cycle.get("farmer_confirmed_stage") or cycle.get("effective_stage") or cycle.get("calculated_stage")
    crop = cycle.get("crop")
    irrigation = field.get("irrigation_type")
    soil_type = field.get("soil_type") or (context.get("soil") or {}).get("source_type")

    # Recent farmer observations (max 3) + latest non-abstained image screening.
    observations = context.get("recent_observations") or []
    latest_condition = next(
        (o.get("field_condition") for o in observations if o.get("field_condition")),
        None,
    )
    image_evidence = _latest_image_evidence(user_id, context)

    # 5. Deterministic analyzers (§6) ---------------------------------------
    assessments: list[Assessment] = []
    assessments.append(analyzers.disease_conducive_weather(crop, stage, weather))
    assessments.append(analyzers.heavy_rain_flooding(crop, stage, weather, latest_condition))
    assessments.append(
        analyzers.heat_stress(crop, stage, weather, irrigated=_has_irrigation(irrigation))
    )
    assessments.append(
        analyzers.water_stress(
            crop,
            stage,
            weather,
            irrigation_type=irrigation,
            soil_type=soil_type,
            field_condition=latest_condition,
        )
    )
    assessments.append(
        analyzers.market_volatility(commodity, market_ctx if include_market else None)
    )

    # 6. Persist append-only with dedup (§29) --------------------------------
    now = utc_now()
    valid_until = _valid_until(now, assessments)
    rows = RiskAssessmentRepository.replace_active_run(
        field_id=field_id,
        user_id=user_id,
        farm_id=(context.get("farm") or {}).get("id"),
        crop_cycle_id=cycle.get("id"),
        assessments=[a.to_dict() for a in assessments],
        rule_version=thresholds.RULES_VERSION,
        valid_until=valid_until,
    )
    duration_ms = int((_time.perf_counter() - started) * 1000)
    return _run_payload(
        field_id,
        context,
        rows,
        cached_run=False,
        duration_ms=duration_ms,
        image_evidence=image_evidence,
        market_ctx=market_ctx,
    )


# ---------------------------------------------------------------------------
# Input gathering
# ---------------------------------------------------------------------------

def _load_market_context(context: Mapping[str, Any], commodity: Optional[str]) -> dict[str, Any]:
    """Fetch official market records via the EXISTING market service (§14, §25)."""
    district = (context.get("farmer") or {}).get("district")
    if not commodity or not district:
        return {"available": False, "reason": "missing_commodity_or_district"}
    try:
        result = market_service.get_mandi_prices(commodity, district=district, field_id=None)
    except Exception:  # provider failure must never fabricate data (§47)
        return {"available": False, "reason": "provider_request_failed"}
    if not result.get("available"):
        return {"available": False, "reason": result.get("reason", "provider_request_failed")}
    return {
        "available": True,
        "provider": result.get("provider"),
        "retrieved_at": result.get("retrieved_at"),
        "records": result.get("records") or [],
    }


def _latest_image_evidence(user_id: int, context: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Latest completed, non-abstained image screening for this crop cycle.

    Supporting evidence only — never treated as confirmed diagnosis (§24).
    """
    from ..models import ImageAnalysis
    from ..extensions import db

    cycle_id = (context.get("crop_cycle") or {}).get("id")
    if not cycle_id:
        return None
    try:
        row = db.session.execute(
            db.select(ImageAnalysis)
            .where(
                ImageAnalysis.crop_cycle_id == cycle_id,
                ImageAnalysis.user_id == user_id,
                ImageAnalysis.status == ImageAnalysis.STATUS_COMPLETED,
                ImageAnalysis.abstained.is_(False),
                ImageAnalysis.deleted_at.is_(None),
            )
            .order_by(ImageAnalysis.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    except Exception:
        return None
    if row is None:
        return None
    return {
        "analysis_id": row.id,
        "predicted_class": row.predicted_class,
        "calibrated_confidence": row.calibrated_confidence,
        "confidence_category": row.confidence_category,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _has_irrigation(irrigation_type: Any) -> Optional[bool]:
    if irrigation_type is None or str(irrigation_type).strip() == "":
        return None
    text = str(irrigation_type).lower()
    keywords = ("canal", "bore", "well", "tube", "sprinkler", "drip", "pump", "lift")
    if any(word in text for word in keywords):
        return True
    if "rain" in text and "fed" in text or text in ("none", "rainfed", "rain-fed"):
        return False
    return None


def _valid_until(now, assessments: list[Assessment]) -> Any:
    """Shortest advisory validity across active assessments; None otherwise."""
    horizon_minutes = 24 * 60
    active = [a for a in assessments if a.status in ("monitor", "elevated", "high", "critical")]
    if not active:
        return None
    return now.replace(microsecond=0) + __import__("datetime").timedelta(minutes=horizon_minutes)


# ---------------------------------------------------------------------------
# Payload assembly
# ---------------------------------------------------------------------------

def _run_payload(
    field_id: int,
    context: Mapping[str, Any],
    rows: list,
    *,
    cached_run: bool,
    duration_ms: int,
    image_evidence: Optional[dict[str, Any]] = None,
    market_ctx: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Farmer-facing response built from PERSISTED rows (§30, §46)."""
    assessments = []
    for row in rows:
        assessments.append(
            {
                "id": row.id,
                "risk_type": row.risk_type,
                "status": row.status,
                "threat": row.threat,
                "probability": row.probability,
                "severity": row.severity,
                "urgency": row.urgency,
                "warning_lead_time_hours": row.warning_lead_time_hours,
                "confidence": row.confidence,
                "confidence_basis": row.confidence_basis,
                "reasons": _loads(row.reasons_json) or [],
                "actions": _loads(row.actions_json) or [],
                "evidence": _loads(row.evidence_json) or [],
                "data_quality": _loads(row.data_quality_json) or {},
                "requires_expert_confirmation": bool(row.requires_expert_confirmation),
                "unavailable_reason": row.unavailable_reason,
                "rule_version": row.rule_version,
                "generated_at": row.generated_at.isoformat() if row.generated_at else None,
                "valid_until": row.valid_until.isoformat() if row.valid_until else None,
            }
        )

    weather_raw = context.get("weather") or {}
    weather_freshness = classify(
        "weather", weather_raw.get("provider_observed_at"), weather_raw.get("retrieved_at")
    )
    overall = _overall_status([a["status"] for a in assessments])

    return {
        "ok": True,
        "field_id": field_id,
        "crop_cycle_id": (context.get("crop_cycle") or {}).get("id"),
        "crop": (context.get("crop_cycle") or {}).get("crop"),
        "overall_status": overall,
        "cached_run": cached_run,
        "duration_ms": duration_ms,
        "weather_freshness": weather_freshness,
        "weather": {
            "available": bool(weather_raw.get("available")),
            "provider": weather_raw.get("provider"),
            "observed_at": weather_raw.get("provider_observed_at"),
            "retrieved_at": weather_raw.get("retrieved_at"),
            "freshness": weather_freshness,
        },
        "market": {
            "available": bool((market_ctx or {}).get("available")),
            "reason": (market_ctx or {}).get("reason"),
        },
        "image_evidence": image_evidence,
        "assessments": assessments,
        "analysis_generated_at": assessments[0]["generated_at"] if assessments else None,
    }


def _overall_status(statuses: list[str]) -> str:
    """Worst active status wins; unavailable types are reported, not hidden (§9)."""
    order = ["critical", "high", "elevated", "monitor", "inactive"]
    for candidate in order:
        if candidate in statuses:
            return candidate
    if "insufficient_data" in statuses and "data_unavailable" in statuses:
        return "insufficient_data"
    if "insufficient_data" in statuses:
        return "insufficient_data"
    if "data_unavailable" in statuses:
        return "data_unavailable"
    return "inactive"


def record_farmer_action(
    assessment,
    *,
    action_status: str,
    farmer_note: Optional[str] = None,
    outcome_note: Optional[str] = None,
) -> dict[str, Any]:
    """Record the farmer's response via the EXISTING farmer_actions flow (§27).

    Creates one Recommendation per active action (first call only) and attaches
    the FarmerAction to it. Never auto-completes an action; outcomes are
    farmer-entered facts, never generated.
    """
    from ..extensions import db

    recommendation_id = getattr(assessment, "recommendation_id", None)

    if recommendation_id is None:
        actions = _loads_json(assessment.actions_json) or []
        primary_action = actions[0] if actions else "Monitor the reported risk."
        rec_payload = {
            "recommendation_type": f"risk_{assessment.risk_type}",
            "action": primary_action,
            "reasons": _loads_json(assessment.reasons_json) or [],
            "evidence": _loads_json(assessment.evidence_json) or [],
            "confidence": {"score": assessment.confidence or 0.0},
            "valid_until": assessment.valid_until.isoformat() if assessment.valid_until else None,
            "requires_expert_confirmation": bool(assessment.requires_expert_confirmation),
        }
        recommendation_id = _create_recommendation(assessment, rec_payload)
        assessment.recommendation_id = recommendation_id
        db.session.commit()

    action = RecommendationRepository.add_action(recommendation_id, data={
        "action_status": action_status,
        "farmer_note": farmer_note,
        "action_taken_at": utc_now() if action_status == "completed" else None,
        "outcome_note": outcome_note,
        "outcome_recorded_at": utc_now() if outcome_note else None,
    })
    return {
        "id": action.id,
        "action_status": action.action_status,
        "farmer_note": action.farmer_note,
        "outcome_note": action.outcome_note,
        "recommendation_id": recommendation_id,
    }


def _create_recommendation(assessment, payload: dict[str, Any]) -> int:
    """Persist the risk's primary action as a structured recommendation."""
    from .recommendation_service import persist_recommendation

    return persist_recommendation(
        assessment.user_id,
        payload,
        farm_id=assessment.farm_id,
        field_id=assessment.field_id,
        crop_cycle_id=assessment.crop_cycle_id,
    )


def _loads_json(text):
    import json as _json

    if not text:
        return []
    try:
        return _json.loads(text)
    except (TypeError, ValueError):
        return []


__all__ = ["analyze_field", "analyze_context", "record_farmer_action", "RISK_ASSESSMENT_TTL_MINUTES"]
