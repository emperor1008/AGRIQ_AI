"""Feedback service (Phase 2 §15): recommendation feedback and outcome tracking.

Rules enforced here:
- Feedback belongs only to the authenticated user (recommendation must be
  owned by the same user before feedback is accepted).
- No feedback is never interpreted as success anywhere in AGRIQ.
- The original recommendation and its evidence are never modified.
"""
from __future__ import annotations

from typing import Any, Optional

from ..core.logging import get_logger
from ..repositories.copilot_repository import FeedbackRepository, RecommendationRepository
from .recommendation_service import get_owned_recommendation

logger = get_logger("services.feedback")

VALID_STATUSES = {"planned", "completed", "skipped", "needs_help"}


class FeedbackError(ValueError):
    """Raised for invalid feedback payloads."""


def record_feedback(user_id: int, recommendation_id: int, data: dict[str, Any]) -> dict[str, Any]:
    """Record owner-verified feedback on a recommendation."""
    recommendation = get_owned_recommendation(recommendation_id, user_id)
    if recommendation is None:
        raise FeedbackError("recommendation_not_found")

    status = str(data.get("status") or "").strip()
    if status not in VALID_STATUSES:
        raise FeedbackError("invalid_status")

    helpfulness = data.get("helpfulness")
    if helpfulness is not None:
        try:
            helpfulness = int(helpfulness)
        except (TypeError, ValueError):
            raise FeedbackError("invalid_helpfulness")
        if not 1 <= helpfulness <= 5:
            raise FeedbackError("invalid_helpfulness")

    feedback = FeedbackRepository.create(
        user_id=user_id,
        recommendation_id=recommendation.id,
        data={
            "status": status,
            "helpfulness": helpfulness,
            "farmer_note": (data.get("farmer_note") or None),
            "outcome": (data.get("outcome") or None),
        },
    )
    # Mirror the action onto farmer_actions (the Phase 1 action log) so the
    # timeline stays consistent; outcome text rides in farmer_note.
    if status in ("completed", "skipped", "needs_help"):
        RecommendationRepository.add_action(recommendation.id, {
            "action_status": status,
            "farmer_note": (data.get("farmer_note") or data.get("outcome") or None),
            "action_taken_at": feedback.created_at if status == "completed" else None,
        })
    logger.info("feedback_recorded recommendation_id=%s user_id=%s status=%s",
                recommendation_id, user_id, status)
    return {
        "id": feedback.id,
        "recommendation_id": feedback.recommendation_id,
        "status": feedback.status,
        "helpfulness": feedback.helpfulness,
        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
    }


def get_owned_feedback(feedback_id: int, user_id: int):
    return FeedbackRepository.get_owned(feedback_id, user_id)


__all__ = ["record_feedback", "get_owned_feedback", "FeedbackError", "VALID_STATUSES"]
