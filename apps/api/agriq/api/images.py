"""Crop-image intelligence API blueprint (Phase 4).

Endpoints (all authenticated; ownership enforced in the repository layer):

- POST   /api/v1/crop-images/analyse                        — upload + screen one image
- GET    /api/v1/crop-images/analyses/<id>                  — owned analysis detail
- DELETE /api/v1/crop-images/analyses/<id>                  — safe (soft) deletion
- POST   /api/v1/crop-images/analyses/<id>/feedback         — farmer feedback (never an expert label)
- POST   /api/v1/crop-images/analyses/<id>/request-expert-review — escalate to expert workflow

Route bodies handle HTTP only (auth, parsing, service calls); validation,
quality gating, model loading and abstention live in ml/ + services.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..core.audit import audit_event
from ..core.config import get_config
from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging import get_logger
from ..core.security import current_user, require_csrf
from ..schemas.image_analysis import validate_analyse_request, validate_feedback
from ..services.image_service import CropImageService

logger = get_logger("api.images")

image_bp = Blueprint("images", __name__)

_service = CropImageService()


def _require_active_user():
    user = current_user()
    if user is None or not user.is_active:
        raise NotFoundError("Sign in to continue.")
    return user


@image_bp.get("/api/v1/crop-images/capabilities")
def image_capabilities():
    """Honest capability probe: reflects whether a registry-approved model
    with a passing checksum exists. Never hardcoded to true."""
    _require_active_user()
    available = _service.available()
    return jsonify({"ok": True, "image_analysis_available": available})


@image_bp.post("/api/v1/crop-images/analyse")
@require_csrf
def analyse_image():
    user = _require_active_user()
    upload = request.files.get("image")
    if upload is None or not upload.filename:
        raise ValidationError("Attach a crop photo to analyse.")

    expected_crop = request.form.get("crop") or (request.get_json(silent=True) or {}).get("crop")
    crop = validate_analyse_request(expected_crop=expected_crop)

    result = _service.analyse_upload(user.id, storage=upload, expected_crop=crop)
    audit_event("image_analyse", user_id=user.id, outcome=result.get("status", "unknown"))
    return jsonify({"ok": True, "analysis": result}), 201


@image_bp.get("/api/v1/crop-images/analyses/<int:analysis_id>")
def get_analysis(analysis_id: int):
    user = _require_active_user()
    result = _service.get_owned(analysis_id, user.id)
    if result is None:
        raise NotFoundError()
    return jsonify({"ok": True, "analysis": result})


@image_bp.delete("/api/v1/crop-images/analyses/<int:analysis_id>")
@require_csrf
def delete_analysis(analysis_id: int):
    user = _require_active_user()
    if not _service.delete_owned(analysis_id, user.id):
        raise NotFoundError()
    audit_event("image_delete", user_id=user.id, outcome="ok")
    return jsonify({"ok": True})


@image_bp.post("/api/v1/crop-images/analyses/<int:analysis_id>/feedback")
@require_csrf
def analysis_feedback(analysis_id: int):
    user = _require_active_user()
    from ..repositories.image_repository import ImageAnalysisRepository, ImageFeedbackRepository

    if ImageAnalysisRepository.get_owned(analysis_id, user.id) is None:
        raise NotFoundError()
    data = request.get_json(silent=True) or request.form or {}
    note = validate_feedback(data.get("farmer_feedback"))
    row = ImageFeedbackRepository.create_farmer_feedback(analysis_id, user.id, note)
    audit_event("image_feedback", user_id=user.id, outcome="ok")
    return jsonify({"ok": True, "feedback_id": row.id}), 201


@image_bp.post("/api/v1/crop-images/analyses/<int:analysis_id>/request-expert-review")
@require_csrf
def request_expert_review(analysis_id: int):
    user = _require_active_user()
    from ..repositories.image_repository import ImageAnalysisRepository, ImageFeedbackRepository

    if ImageAnalysisRepository.get_owned(analysis_id, user.id) is None:
        raise NotFoundError()
    row = ImageFeedbackRepository.request_expert_review(analysis_id, user.id)
    audit_event("image_expert_review_request", user_id=user.id, outcome="ok")
    return jsonify({"ok": True, "request_id": row.id, "review_status": row.review_status}), 201


__all__ = ["image_bp"]
