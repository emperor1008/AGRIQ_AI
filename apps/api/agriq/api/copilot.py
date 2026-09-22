"""Versioned copilot API (Phase 2 §2).

Endpoints:

- POST /api/v1/copilot/messages          — one copilot turn (full or compact)
- GET  /api/v1/copilot/conversations/<ref> — conversation history (owner-only)
- POST /api/v1/recommendations/<id>/feedback — feedback/outcome on a recommendation

Route bodies handle HTTP only: authentication, payload parsing, calling the
orchestrator/services, serialisation and status codes. No agricultural
calculation, provider call, prompt construction or DB query lives here.
user_id always comes from the session — never from the request body.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..core.audit import audit_event
from ..core.config import get_config
from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging import get_logger
from ..core.security import current_user, require_csrf
from ..repositories.copilot_repository import ConversationRepository
from ..schemas.copilot import parse_copilot_message, parse_feedback_payload
from ..services import copilot_orchestrator, feedback_service
from ..services.recommendation_service import (
    get_owned_recommendation,
    recommendation_to_dict,
)

logger = get_logger("api.copilot")

copilot_bp = Blueprint("copilot", __name__)


def _require_active_user():
    user = current_user()
    if user is None or not user.is_active:
        raise NotFoundError("Sign in to continue.")
    return user


@copilot_bp.post("/api/v1/copilot/messages")
@require_csrf
def post_message():
    user = _require_active_user()
    payload = request.get_json(silent=True) or request.form
    data = parse_copilot_message(payload)
    response_mode = "compact" if request.args.get("response_mode") == "compact" else "full"

    result = copilot_orchestrator.run_copilot(
        user_id=user.id,
        profile_id=user.id,  # build_farmer_context resolves the profile internally
        question=data["question"],
        language=data["language"],
        field_id=data["field_id"],
        crop_cycle_id=data["crop_cycle_id"],
        conversation_ref=data["conversation_id"],
        response_mode=response_mode,
        config=get_config(),
    )
    if not result.get("ok"):
        # Orchestrator-level guards (empty question, foreign ids, no profile)
        # return a 400-class body; NotFoundError for foreign ids leaks nothing.
        if result.get("error") == "not_found":
            raise NotFoundError()
        return jsonify(result), 400

    audit_event("copilot_message", user_id=user.id,
                intent=result.get("intent"), outcome="ok")
    return jsonify(result), 200


@copilot_bp.get("/api/v1/copilot/conversations/<conversation_ref>")
def get_conversation(conversation_ref: str):
    user = _require_active_user()
    conversation = ConversationRepository.get_owned(conversation_ref, user.id)
    if conversation is None:
        raise NotFoundError()
    messages = ConversationRepository.recent_messages(conversation.id, limit=50)
    return jsonify({
        "ok": True,
        "conversation_id": conversation.uuid or str(conversation.id),
        "messages": [
            {
                "id": m.uuid or str(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "sources": m.sources_json,
            }
            for m in messages
        ],
    })


@copilot_bp.post("/api/v1/recommendations/<int:recommendation_id>/feedback")
@require_csrf
def post_feedback(recommendation_id: int):
    user = _require_active_user()
    data = parse_feedback_payload(request.get_json(silent=True) or request.form)
    try:
        feedback = feedback_service.record_feedback(user.id, recommendation_id, data)
    except feedback_service.FeedbackError as exc:
        # Internal codes are translated to farmer-facing text here; nothing
        # raw from the service layer reaches the response body.
        _FRIENDLY = {
            "recommendation_not_found": None,  # handled below as a 404
            "invalid_status": "Choose a valid action status for your feedback.",
            "invalid_helpfulness": "Helpfulness must be a rating from 1 to 5.",
        }
        if str(exc) == "recommendation_not_found":
            raise NotFoundError()
        raise ValidationError(_FRIENDLY.get(str(exc), "We could not save that feedback. Please check the details and try again."))
    audit_event("recommendation_feedback", user_id=user.id,
                recommendation_id=recommendation_id, status=feedback["status"],
                outcome="ok")
    return jsonify({"ok": True, "feedback": feedback}), 201


@copilot_bp.get("/api/v1/recommendations/<int:recommendation_id>")
def get_recommendation(recommendation_id: int):
    user = _require_active_user()
    recommendation = get_owned_recommendation(recommendation_id, user.id)
    if recommendation is None:
        raise NotFoundError()
    return jsonify({"ok": True, "recommendation": recommendation_to_dict(recommendation)})


__all__ = ["copilot_bp"]
