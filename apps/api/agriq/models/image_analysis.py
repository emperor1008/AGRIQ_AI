"""Phase 4 models: validated crop-image intelligence.

- ImageAnalysis rows are owned by exactly one user (user_id) and optionally
  link to the farm/field/crop-cycle context that was shared with the copilot.
- Original images are preserved (never overwritten); the processed copy is
  EXIF-stripped and orientation-normalised. Storage keys are random; images
  live in private storage, never under the public static tree.
- Farmer feedback is never an expert label: expert fields are separate and
  NULL until a real review happens.
- Abstention is a correct outcome: ``abstained=True`` with a recorded reason.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.utcnow()


class ImageAnalysis(db.Model):
    """One crop-image screening run (possible condition, never a diagnosis)."""

    __tablename__ = "image_analyses"

    STATUS_COMPLETED = "completed"
    STATUS_REJECTED = "rejected"
    STATUS_UNAVAILABLE = "unavailable"
    STATUS_DELETED = "deleted"
    STATUSES = {STATUS_COMPLETED, STATUS_REJECTED, STATUS_UNAVAILABLE, STATUS_DELETED}

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    farm_id = db.Column(db.Integer, db.ForeignKey("farms.id"), nullable=True)
    field_id = db.Column(db.Integer, db.ForeignKey("fields.id"), nullable=True)
    crop_cycle_id = db.Column(db.Integer, db.ForeignKey("crop_cycles.id"), nullable=True)
    observation_id = db.Column(db.Integer, db.ForeignKey("field_observations.id"), nullable=True)

    original_storage_key = db.Column(db.String(255), nullable=True)
    processed_storage_key = db.Column(db.String(255), nullable=True)
    original_checksum = db.Column(db.String(64), nullable=True)

    model_name = db.Column(db.String(120), nullable=True)
    model_version = db.Column(db.String(40), nullable=True)
    dataset_manifest_version = db.Column(db.String(120), nullable=True)

    expected_crop = db.Column(db.String(40), nullable=False)
    predicted_class = db.Column(db.String(60), nullable=True)
    calibrated_confidence = db.Column(db.Float, nullable=True)
    confidence_category = db.Column(db.String(30), nullable=True)
    abstained = db.Column(db.Boolean, nullable=False, default=False)
    abstention_reason = db.Column(db.String(60), nullable=True)

    image_quality_json = db.Column(db.Text, nullable=True)
    predictions_json = db.Column(db.Text, nullable=True)
    explanation_json = db.Column(db.Text, nullable=True)
    requires_expert_confirmation = db.Column(db.Boolean, nullable=False, default=True)

    status = db.Column(db.String(20), nullable=False, default=STATUS_COMPLETED, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship("User", foreign_keys=[user_id])

    def predictions(self) -> list[dict[str, Any]]:
        import json

        return json.loads(self.predictions_json) if self.predictions_json else []

    def explanations(self) -> list[str]:
        import json

        return json.loads(self.explanation_json) if self.explanation_json else []

    def quality(self) -> dict[str, Any]:
        import json

        return json.loads(self.image_quality_json) if self.image_quality_json else {}

    def to_json(self) -> dict[str, Any]:
        """Farmer-facing payload. No fabricated values: abstained rows carry
        no probabilities, unavailable rows carry no model identity."""
        import json

        data: dict[str, Any] = {
            "analysis_id": str(self.id),
            "status": self.status,
            "crop": {"expected": self.expected_crop, "supported": self.status == self.STATUS_COMPLETED},
            "image_quality": json.loads(self.image_quality_json) if self.image_quality_json else {},
            "abstained": bool(self.abstained),
            "abstention_reason": self.abstention_reason,
            "requires_expert_confirmation": bool(self.requires_expert_confirmation),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "explanation": json.loads(self.explanation_json) if self.explanation_json else [],
            "limitations": [
                "Image screening cannot confirm a laboratory diagnosis.",
                "Model validation for local field conditions is in progress.",
            ],
        }
        if self.status == self.STATUS_COMPLETED and not self.abstained:
            data["model"] = {"name": self.model_name, "version": self.model_version}
            data["predictions"] = self.predictions()
            data["confidence_category"] = self.confidence_category
        else:
            data["model"] = None
            data["predictions"] = []
            if self.status == self.STATUS_UNAVAILABLE:
                data["message"] = "Image analysis is not currently available."
            elif self.status == self.STATUS_REJECTED:
                data["message"] = (
                    "AGRIQ could not identify this condition reliably. "
                    "Please retake the image or consult an agriculture expert."
                )
        return data


class ImageAnalysisFeedback(db.Model):
    """Farmer/expert feedback on an analysis. Farmer feedback is never an
    expert label (separate columns, separate review workflow)."""

    __tablename__ = "image_analysis_feedback"

    REVIEW_PENDING = "pending"
    REVIEW_APPROVED = "approved"
    REVIEW_REJECTED = "rejected"
    REVIEW_STATUSES = {REVIEW_PENDING, REVIEW_APPROVED, REVIEW_REJECTED}

    id = db.Column(db.Integer, primary_key=True)
    analysis_id = db.Column(db.Integer, db.ForeignKey("image_analyses.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    farmer_feedback = db.Column(db.Text, nullable=True)
    expert_label = db.Column(db.String(60), nullable=True)
    expert_reviewer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    review_status = db.Column(db.String(20), nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)


__all__ = ["ImageAnalysis", "ImageAnalysisFeedback"]
