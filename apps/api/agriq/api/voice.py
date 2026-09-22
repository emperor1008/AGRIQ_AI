"""Voice API blueprint (Phase 3).

Endpoints (all authenticated; user id always from the session):

- GET    /api/v1/voice/capabilities                 — real per-language capability map
- GET/POST /api/v1/voice/consent                    — consent status / give consent
- POST   /api/v1/voice/consent/revoke               — revoke future voice processing
- POST   /api/v1/voice/sessions                     — start a voice session
- POST   /api/v1/voice/sessions/{id}/audio          — upload recording (multipart)
- GET    /api/v1/voice/sessions/{id}/transcription  — run/report ASR state
- POST   /api/v1/voice/sessions/{id}/confirm        — farmer-confirmed transcript
- POST   /api/v1/voice/sessions/{id}/ask            — hand off to the Phase 2 copilot
- DELETE /api/v1/voice/sessions/{id}/audio          — delete stored recording
- POST   /api/v1/voice/synthesise                   — TTS for an owned answer
- GET    /api/v1/voice/audio/{audio_id}             — stream owned synthesised audio

Route bodies handle HTTP only (auth, parsing, service calls, serialisation);
all pipeline logic lives in services, provider calls in integrations.
"""
from __future__ import annotations

from flask import Blueprint, Response, jsonify, request, send_file
from pathlib import Path

from ..core.audit import audit_event
from ..core.config import get_config
from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging import get_logger
from ..core.security import current_user, require_csrf
from ..schemas.voice import (
    parse_confirm_payload,
    parse_consent_payload,
    parse_session_start,
    parse_synthesis_payload,
)
from ..services import voice_consent_service, voice_orchestrator

logger = get_logger("api.voice")

voice_bp = Blueprint("voice", __name__)


def _require_active_user():
    user = current_user()
    if user is None or not user.is_active:
        raise NotFoundError("Sign in to continue.")
    return user


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

@voice_bp.get("/api/v1/voice/capabilities")
def get_capabilities():
    _require_active_user()
    return jsonify({"ok": True, **voice_orchestrator.capabilities(get_config())})


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

@voice_bp.get("/api/v1/voice/consent")
def get_consent():
    user = _require_active_user()
    return jsonify({"ok": True, "consent": voice_consent_service.get_active_consent(user.id)})


@voice_bp.post("/api/v1/voice/consent")
@require_csrf
def post_consent():
    user = _require_active_user()
    data = parse_consent_payload(request.get_json(silent=True) or request.form)
    consent = voice_consent_service.give_consent(user.id, data)
    audit_event("voice_consent", user_id=user.id,
                version=consent["consent_version"], outcome="ok")
    return jsonify({"ok": True, "consent": consent}), 201


@voice_bp.post("/api/v1/voice/consent/revoke")
@require_csrf
def revoke_consent():
    user = _require_active_user()
    consent = voice_consent_service.revoke_consent(user.id)
    audit_event("voice_consent_revoke", user_id=user.id, outcome="ok")
    return jsonify({"ok": True, "consent": consent})


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

@voice_bp.post("/api/v1/voice/sessions")
@require_csrf
def start_session():
    user = _require_active_user()
    data = parse_session_start(request.get_json(silent=True) or request.form)
    session = voice_orchestrator.start_session(user.id, data, get_config())
    audit_event("voice_session_start", user_id=user.id,
                language=session["language_requested"], outcome="ok")
    return jsonify({"ok": True, "session": session}), 201


@voice_bp.post("/api/v1/voice/sessions/<session_ref>/audio")
@require_csrf
def upload_audio(session_ref: str):
    user = _require_active_user()
    upload = request.files.get("audio")
    if upload is None or not upload.filename:
        raise ValidationError("Attach the recorded audio file.")
    result = voice_orchestrator.upload_audio(session_ref, user.id, upload, get_config())
    audit_event("voice_audio_upload", user_id=user.id, outcome="ok")
    return jsonify({"ok": True, **result}), 201


@voice_bp.get("/api/v1/voice/sessions/<session_ref>/transcription")
def get_transcription(session_ref: str):
    user = _require_active_user()
    result = voice_orchestrator.transcribe_session(session_ref, user.id, get_config())
    status = 200 if result.get("status") != "unavailable" else 503
    return jsonify({"ok": result.get("status") == "completed", **result}), status


@voice_bp.post("/api/v1/voice/sessions/<session_ref>/confirm")
@require_csrf
def confirm_transcript(session_ref: str):
    user = _require_active_user()
    data = parse_confirm_payload(request.get_json(silent=True) or request.form)
    result = voice_orchestrator.confirm_transcript(
        session_ref, user.id, data["confirmed_transcript"], data["language"]
    )
    audit_event("voice_transcript_confirm", user_id=user.id, outcome="ok")
    return jsonify({"ok": True, **result})


@voice_bp.post("/api/v1/voice/sessions/<session_ref>/ask")
@require_csrf
def ask_copilot(session_ref: str):
    user = _require_active_user()
    result = voice_orchestrator.ask_copilot(session_ref, user.id, get_config())
    audit_event("voice_ask_copilot", user_id=user.id, outcome="ok")
    return jsonify({"ok": True, **result})


@voice_bp.delete("/api/v1/voice/sessions/<session_ref>/audio")
@require_csrf
def delete_audio(session_ref: str):
    user = _require_active_user()
    result = voice_orchestrator.delete_recording(session_ref, user.id, get_config())
    audit_event("voice_audio_delete", user_id=user.id, outcome="ok")
    return jsonify({"ok": True, **result})


# ---------------------------------------------------------------------------
# Synthesis / playback
# ---------------------------------------------------------------------------

@voice_bp.post("/api/v1/voice/synthesise")
@require_csrf
def synthesise():
    user = _require_active_user()
    data = parse_synthesis_payload(request.get_json(silent=True) or request.form)
    result = voice_orchestrator.synthesise_message(
        user.id, data["message_id"], data["language"], get_config()
    )
    if result.get("status") == "unavailable":
        return jsonify({"ok": False, **result}), 503
    audit_event("voice_synthesise", user_id=user.id, outcome="ok")
    return jsonify({"ok": True, **result})


@voice_bp.get("/api/v1/voice/audio/<audio_ref>")
def stream_audio(audio_ref: str):
    """Owner-only audio streaming (never a public static URL)."""
    user = _require_active_user()
    from ..repositories.voice_repository import SynthesisedAudioRepository

    audio = SynthesisedAudioRepository.get_owned(audio_ref, user.id)
    if audio is None or not audio.is_available or not audio.storage_key:
        raise NotFoundError()
    config = get_config()
    path = Path(config.get("VOICE_TEMP_STORAGE_PATH") or "voice_audio") / audio.storage_key
    if not path.exists():
        raise NotFoundError()
    return send_file(path, mimetype=audio.format, conditional=True)


__all__ = ["voice_bp"]
