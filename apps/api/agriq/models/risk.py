"""Risk-intelligence persistence models (Phase 5).

One row per generated risk assessment. Assessments are append-only: a newer
analysis supersedes (never overwrites) an older one via ``record_status`` +
``superseded_by_id`` so risk history is preserved verbatim.

Probability (likelihood of the condition) and confidence (trust in the
assessment quality) are stored separately and must never be conflated.
Missing values stay NULL — never fabricated.
"""
from __future__ import annotations

from datetime import datetime

from ..extensions import db


def _utcnow() -> datetime:
    from ..core.time import utc_now

    return utc_now()


class RiskAssessment(db.Model):
    """One structured risk evaluation for a field at a point in time."""

    __tablename__ = "risk_assessments"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    farm_id = db.Column(db.Integer, db.ForeignKey("farms.id"), nullable=True)
    field_id = db.Column(db.Integer, db.ForeignKey("fields.id"), nullable=False, index=True)
    crop_cycle_id = db.Column(db.Integer, db.ForeignKey("crop_cycles.id"), nullable=True)
    recommendation_id = db.Column(db.Integer, db.ForeignKey("recommendations.id"), nullable=True)

    run_group = db.Column(db.String(32), nullable=True, index=True)  # groups one analysis run

    risk_type = db.Column(db.String(60), nullable=False, index=True)
    # Risk status: inactive | monitor | elevated | high | critical
    #              | data_unavailable | insufficient_data
    status = db.Column(db.String(30), nullable=False)
    # Record lifecycle: active | superseded | expired | resolved
    record_status = db.Column(db.String(20), nullable=False, default="active", index=True)
    superseded_by_id = db.Column(db.Integer, db.ForeignKey("risk_assessments.id"), nullable=True)

    threat = db.Column(db.String(160), nullable=True)
    # Rule-derived likelihood estimate, banded to 0.05. NULL when insufficient.
    probability = db.Column(db.Float, nullable=True)
    severity = db.Column(db.String(30), nullable=True)
    urgency = db.Column(db.String(60), nullable=True)
    warning_lead_time_hours = db.Column(db.Integer, nullable=True)
    confidence = db.Column(db.Float, nullable=True)
    confidence_basis = db.Column(db.Text, nullable=True)

    reasons_json = db.Column(db.Text, nullable=True)
    actions_json = db.Column(db.Text, nullable=True)
    evidence_json = db.Column(db.Text, nullable=True)
    data_quality_json = db.Column(db.Text, nullable=True)

    generated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    valid_until = db.Column(db.DateTime(timezone=True), nullable=True)

    model_version = db.Column(db.String(60), nullable=False, default="rule-v1")
    rule_version = db.Column(db.String(60), nullable=False)
    requires_expert_confirmation = db.Column(db.Boolean, nullable=False, default=False)
    unavailable_reason = db.Column(db.String(80), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RiskAssessment {self.id} {self.risk_type} {self.status} field={self.field_id}>"


__all__ = ["RiskAssessment"]
