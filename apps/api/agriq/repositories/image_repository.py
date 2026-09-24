"""Ownership-scoped repositories for Phase 4 image intelligence.

A foreign analysis is indistinguishable from a missing one (returns None →
404): the same invariant used by every Phase 1–3 repository.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from ..extensions import db
from ..models.image_analysis import ImageAnalysis, ImageAnalysisFeedback


class ImageAnalysisRepository:
    """image_analyses data access scoped by user."""

    @staticmethod
    def create(user_id: int, data: dict[str, Any]) -> ImageAnalysis:
        analysis = ImageAnalysis(user_id=user_id, **data)
        db.session.add(analysis)
        db.session.commit()
        return analysis

    @staticmethod
    def get_owned(analysis_id: int, user_id: int) -> Optional[ImageAnalysis]:
        analysis = db.session.get(ImageAnalysis, analysis_id)
        if analysis is None or analysis.user_id != user_id:
            return None
        if analysis.status == ImageAnalysis.STATUS_DELETED:
            return None  # soft-deleted reads as missing, history preserved
        return analysis

    @staticmethod
    def soft_delete(analysis: ImageAnalysis) -> None:
        """Safe deletion: mark deleted, never destroy agricultural history."""
        analysis.status = ImageAnalysis.STATUS_DELETED
        analysis.deleted_at = db.func.now()
        db.session.commit()

    @staticmethod
    def recent_for_user(user_id: int, limit: int = 10) -> list[ImageAnalysis]:
        stmt = (
            db.select(ImageAnalysis)
            .where(
                ImageAnalysis.user_id == user_id,
                ImageAnalysis.status != ImageAnalysis.STATUS_DELETED,
            )
            .order_by(ImageAnalysis.created_at.desc())
            .limit(limit)
        )
        return list(db.session.execute(stmt).scalars())


class ImageFeedbackRepository:
    """image_analysis_feedback data access (owner-scoped; farmer feedback is
    never an expert label)."""

    @staticmethod
    def create_farmer_feedback(analysis_id: int, user_id: int, farmer_feedback: str) -> ImageAnalysisFeedback:
        row = ImageAnalysisFeedback(
            analysis_id=analysis_id,
            user_id=user_id,
            farmer_feedback=farmer_feedback,
        )
        db.session.add(row)
        db.session.commit()
        return row

    @staticmethod
    def request_expert_review(analysis_id: int, user_id: int) -> ImageAnalysisFeedback:
        """Raise an expert-review flag row; expert fields stay NULL until a
        real reviewer records a label."""
        row = ImageAnalysisFeedback(
            analysis_id=analysis_id,
            user_id=user_id,
            review_status=ImageAnalysisFeedback.REVIEW_PENDING,
        )
        db.session.add(row)
        db.session.commit()
        return row

    @staticmethod
    def get_owned(feedback_id: int, user_id: int) -> Optional[ImageAnalysisFeedback]:
        row = db.session.get(ImageAnalysisFeedback, feedback_id)
        if row is None or row.user_id != user_id:
            return None
        return row


def _loads(text: str | None) -> Any:
    return json.loads(text) if text else None


__all__ = ["ImageAnalysisRepository", "ImageFeedbackRepository"]
