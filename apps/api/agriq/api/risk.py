"""Risk API blueprint (Phase 5 §30).

Endpoints (all authenticated; user id always from the session):

- GET  /api/v1/risk/fields/<field_id>/current   — latest persisted run
- GET  /api/v1/risk/fields/<field_id>/history   — append-only history
- POST /api/v1/risk/fields/<field_id>/analyze   — run the engine (idempotent)
- GET  /api/v1/risk/assessments/<risk_id>       — one owned assessment
- POST /api/v1/risk/assessments/<risk_id>/action — farmer action tracking (§27)

Route bodies handle HTTP only (auth, parsing, ownership, serialisation); all
risk logic lives in the domain analyzers and risk_service. A foreign
field/assessment id is indistinguishable from a missing one (404).
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..core.exceptions import NotFoundError, ValidationError
from ..core.security import current_user, require_csrf
from ..domain.risk_engine.base import PROBABILITY_INTERPRETATION
from ..repositories.risk_repository import RiskAssessmentRepository
from ..services import risk_service

risk_bp = Blueprint("risk", __name__)

_ACTION_STATUSES = {"planned", "completed", "skipped", "needs_help"}


def _require_active_user():
    user = current_user()
    if user is None or not user.is_active:
        raise NotFoundError("Sign in to continue.")
    return user


# ---------------------------------------------------------------------------
# Field-scoped endpoints
# ---------------------------------------------------------------------------

@risk_bp.get("/api/v1/risk/fields/<int:field_id>/current")
def get_current(field_id: int):
    user = _require_active_user()
    rows = RiskAssessmentRepository.active_run_for_field(field_id, user.id)
    if not rows:
        raise NotFoundError("No risk analysis is stored for this field yet.")
    return jsonify(
        {
            "ok": True,
            "run_group": rows[0].run_group,
            "assessments": [_row_to_dict(r) for r in rows],
        }
    )


@risk_bp.get("/api/v1/risk/fields/<int:field_id>/history")
def get_history(field_id: int):
    user = _require_active_user()
    # History reads require at least one assessment — otherwise the field is
    # either missing or foreign, and both are 404 (no existence leak).
    rows = RiskAssessmentRepository.history_for_field(field_id, user.id, 1)
    if not rows:
        raise NotFoundError("No risk history is stored for this field.")
    limit = min(int(request.args.get("limit", 50) or 50), 200)
    rows = RiskAssessmentRepository.history_for_field(field_id, user.id, limit)
    return jsonify(
        {"ok": True, "history": [_row_to_dict(r) for r in rows]}
    )


@risk_bp.post("/api/v1/risk/fields/<int:field_id>/analyze")
@require_csrf
def analyze(field_id: int):
    user = _require_active_user()
    payload = request.get_json(silent=True) or {}
    try:
        result = risk_service.analyze_field(
            user.id,
            field_id,
            farm_id=payload.get("farm_id"),
            crop_cycle_id=payload.get("crop_cycle_id"),
            include_market=bool(payload.get("include_market", False)),
            force=bool(payload.get("force", False)),
        )
    except PermissionError:
        # Foreign field/cycle is indistinguishable from missing (§30).
        raise NotFoundError("Field not found for your account.")
    return jsonify(result)


# ---------------------------------------------------------------------------
# Assessment-scoped endpoints
# ---------------------------------------------------------------------------

@risk_bp.get("/api/v1/risk/assessments/<int:risk_id>")
def get_assessment(risk_id: int):
    user = _require_active_user()
    row = RiskAssessmentRepository.get_owned(risk_id, user.id)
    if row is None:
        raise NotFoundError("Risk assessment not found.")
    return jsonify({"ok": True, "assessment": _row_to_dict(row)})


@risk_bp.post("/api/v1/risk/assessments/<int:risk_id>/action")
@require_csrf
def record_action(risk_id: int):
    """Record the farmer's response through the existing farmer_actions flow."""
    user = _require_active_user()
    row = RiskAssessmentRepository.get_owned(risk_id, user.id)
    if row is None:
        raise NotFoundError("Risk assessment not found.")

    payload = request.get_json(silent=True) or {}
    status = str(payload.get("action_status") or "").strip()
    if status not in _ACTION_STATUSES:
        raise ValidationError("Choose a valid action status.")
    outcome = risk_service.record_farmer_action(
        row,
        action_status=status,
        farmer_note=(payload.get("farmer_note") or None),
        outcome_note=(payload.get("outcome_note") or None),
    )
    return jsonify({"ok": True, "action": outcome})


def _row_to_dict(row) -> dict:
    import json as _json

    def _loads(text):
        try:
            return _json.loads(text) if text else []
        except (TypeError, ValueError):
            return []

    return {
        "id": row.id,
        "field_id": row.field_id,
        "crop_cycle_id": row.crop_cycle_id,
        "risk_type": row.risk_type,
        "status": row.status,
        "record_status": row.record_status,
        "threat": row.threat,
        "probability": row.probability,
        "severity": row.severity,
        "urgency": row.urgency,
        "warning_lead_time_hours": row.warning_lead_time_hours,
        "confidence": row.confidence,
        "confidence_basis": row.confidence_basis,
        "reasons": _loads(row.reasons_json),
        "actions": _loads(row.actions_json),
        "evidence": _loads(row.evidence_json),
        "data_quality": _loads(row.data_quality_json) or {},
        "requires_expert_confirmation": bool(row.requires_expert_confirmation),
        "unavailable_reason": row.unavailable_reason,
        "rule_version": row.rule_version,
        # Provenance: what produced the number and what it may be read as (§7, §17).
        "assessment_method": row.assessment_method,
        "probability_kind": row.probability_kind,
        "calibration_status": row.calibration_status,
        "probability_interpretation": PROBABILITY_INTERPRETATION.get(row.probability_kind),
        # Evaluation dimensions snapshotted at assessment time (§13).
        "crop": row.crop_name,
        "growth_stage": row.growth_stage,
        "district": row.district,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "valid_until": row.valid_until.isoformat() if row.valid_until else None,
    }
