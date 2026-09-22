"""Recommendation service (Phase 2 §11): persistence and owner-scoped reads.

Every field-specific recommendation persisted here carries reasons, evidence
with real sources/timestamps and the documented confidence result. Original
recommendations are never rewritten by feedback.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from ..core.time import utc_now
from ..repositories.copilot_repository import RecommendationRepository


def persist_recommendation(
    user_id: int,
    payload: dict[str, Any],
    *,
    farm_id: Optional[int] = None,
    field_id: Optional[int] = None,
    crop_cycle_id: Optional[int] = None,
) -> int:
    """Store one structured recommendation; returns its id."""
    confidence = payload.get("confidence") or {}
    recommendation = RecommendationRepository.create(user_id=user_id, data={
        "farm_id": farm_id,
        "field_id": field_id,
        "crop_cycle_id": crop_cycle_id,
        "recommendation_type": str(payload.get("recommendation_type") or "advisory"),
        "action": str(payload.get("action") or "").strip()[:1000],
        "reasons_json": json.dumps(payload.get("reasons") or [], ensure_ascii=False),
        "evidence_json": json.dumps(payload.get("evidence") or [], ensure_ascii=False),
        "confidence": float(confidence.get("score", 0.0)),
        "valid_from": utc_now(),
        "valid_until": _parse_iso(payload.get("valid_until")),
        "requires_expert_confirmation": bool(payload.get("requires_expert_confirmation")),
    })
    return recommendation.id


def recommendation_to_dict(recommendation) -> dict[str, Any]:
    """Serialise a Recommendation row (parses JSON columns)."""
    return {
        "id": recommendation.id,
        "recommendation_type": recommendation.recommendation_type,
        "action": recommendation.action,
        "reasons": json.loads(recommendation.reasons_json or "[]"),
        "evidence": json.loads(recommendation.evidence_json or "[]"),
        "confidence": recommendation.confidence,
        "valid_from": recommendation.valid_from.isoformat() if recommendation.valid_from else None,
        "valid_until": recommendation.valid_until.isoformat() if recommendation.valid_until else None,
        "requires_expert_confirmation": bool(recommendation.requires_expert_confirmation),
        "created_at": recommendation.created_at.isoformat() if recommendation.created_at else None,
    }


def get_owned_recommendation(recommendation_id: int, user_id: int):
    """Owner-only fetch — another user's id is indistinguishable from missing."""
    return RecommendationRepository.get_owned(recommendation_id, user_id)


def recent_recommendations(cycle_id: Optional[int], user_id: int, limit: int = 5):
    """Previous recommendations for personalisation (owner-scoped)."""
    if cycle_id:
        rows = RecommendationRepository.recent_for_cycle(cycle_id, user_id, limit)
    else:
        rows = RecommendationRepository.recent_for_user(user_id, limit)
    return [recommendation_to_dict(r) for r in rows]


def _parse_iso(value: Any):
    if not value:
        return None
    from datetime import datetime
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        return None


__all__ = ["persist_recommendation", "recommendation_to_dict",
           "get_owned_recommendation", "recent_recommendations"]
