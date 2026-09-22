"""Request/response schemas for the voice API (Phase 3).

Server-side validation only: language codes are normalised through the
closed supported set, session ids must be valid, and transcript text is
length-limited and cleaned. No user id is ever accepted from the payload.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..core.exceptions import ValidationError
from ..core.text import clean_text
from .copilot import parse_copilot_message  # noqa: F401  (re-export for voice ask flow)


def parse_session_start(payload: Mapping[str, Any]) -> dict[str, Any]:
    """POST /api/v1/voice/sessions body."""
    from ..services import language_service

    language_raw = str(payload.get("language") or "").strip()
    if not language_raw:
        raise ValidationError("Select a language before recording.")
    if not language_service.is_supported(language_raw):
        raise ValidationError(
            "That language is not supported for voice yet. Please choose Odia, Hindi or English (India)."
        )
    data: dict[str, Any] = {
        "language": language_service.normalise(language_raw),
        "field_id": _optional_int(payload.get("field_id"), "field_id"),
        "crop_cycle_id": _optional_int(payload.get("crop_cycle_id"), "crop_cycle_id"),
        "retain_audio": bool(payload.get("retain_audio", False)),
    }
    return data


def parse_confirm_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """POST /api/v1/voice/sessions/{id}/confirm body."""
    confirmed = clean_text(str(payload.get("confirmed_transcript") or ""), 2000)
    if not confirmed:
        raise ValidationError("Review or type your question before sending it.")
    language = str(payload.get("language") or "").strip() or None
    return {"confirmed_transcript": confirmed, "language": language}


def parse_synthesis_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """POST /api/v1/voice/synthesise body."""
    message_id = str(payload.get("message_id") or "").strip()
    if not message_id:
        raise ValidationError("Specify which answer to read aloud.")
    language = str(payload.get("language") or "").strip()
    if not language:
        raise ValidationError("Select a language for audio playback.")
    from ..services import language_service
    if not language_service.is_supported(language):
        raise ValidationError("That language is not supported for audio playback.")
    return {"message_id": message_id, "language": language_service.normalise(language)}


def parse_consent_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """POST /api/v1/voice/consent body (absent flags are False, never true)."""
    return {
        "speech_provider_processing_allowed": bool(payload.get("speech_provider_processing_allowed", False)),
        "evaluation_use_allowed": bool(payload.get("evaluation_use_allowed", False)),
        "audio_retention_allowed": bool(payload.get("audio_retention_allowed", False)),
    }


def _optional_int(value: Any, key: str) -> int | None:
    if value in (None, ""):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{key} must be a valid id.")
    if number <= 0:
        raise ValidationError(f"{key} must be a valid id.")
    return number


__all__ = [
    "parse_session_start", "parse_confirm_payload",
    "parse_synthesis_payload", "parse_consent_payload",
]
