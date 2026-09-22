"""Voice consent service (Phase 3).

No recording is processed without an active consent row. The consent notice
version is bumped whenever the notice text changes materially; stored
records keep the exact version the farmer saw.
"""
from __future__ import annotations

from typing import Any

from ..core.exceptions import ValidationError
from ..core.logging import get_logger
from ..repositories.voice_repository import VoiceConsentRepository

logger = get_logger("services.voice_consent")

#: Current consent notice version (docs/VOICE_PRIVACY.md §notice-text).
CONSENT_VERSION = "voice-consent-v1"


class ConsentError(ValidationError):
    """Consent-specific validation error (farmer-friendly message)."""


def give_consent(user_id: int, data: dict[str, Any]) -> dict[str, Any]:
    """Record a fresh consent (revokes any previous one implicitly by
    creating a newer version). Booleans default to False — an absent
    checkbox is never treated as agreement."""
    speech_allowed = bool(data.get("speech_provider_processing_allowed", False))
    if not speech_allowed:
        raise ConsentError(
            "Voice processing needs your agreement to send recordings to the speech service."
        )
    consent = VoiceConsentRepository.create(user_id, {
        "consent_version": CONSENT_VERSION,
        "speech_provider_processing_allowed": True,
        "evaluation_use_allowed": bool(data.get("evaluation_use_allowed", False)),
        "audio_retention_allowed": bool(data.get("audio_retention_allowed", False)),
    })
    logger.info("voice_consent_given user_id=%s version=%s", user_id, consent.consent_version)
    return _to_dict(consent)


def revoke_consent(user_id: int) -> dict[str, Any] | None:
    """Revoke the active consent (future processing only)."""
    consent = VoiceConsentRepository.active_for_user(user_id)
    if consent is None:
        return None
    VoiceConsentRepository.revoke(consent)
    logger.info("voice_consent_revoked user_id=%s", user_id)
    return _to_dict(consent)


def get_active_consent(user_id: int) -> dict[str, Any] | None:
    consent = VoiceConsentRepository.active_for_user(user_id)
    return _to_dict(consent) if consent else None


def require_consent(user_id: int) -> dict[str, Any]:
    """Consent gate: raises ConsentError when no active consent exists."""
    consent = VoiceConsentRepository.active_for_user(user_id)
    if consent is None:
        raise ConsentError(
            "Please review and accept the voice privacy notice before using voice input."
        )
    return _to_dict(consent)


def retention_allowed(consent: dict[str, Any] | None, session_retain_flag: bool) -> bool:
    """Audio is retained only when BOTH the farmer consented AND the session
    explicitly asked for retention (default is False — never retained)."""
    if not session_retain_flag:
        return False
    return bool(consent and consent.get("audio_retention_allowed"))


def _to_dict(consent) -> dict[str, Any]:
    return {
        "id": consent.id,
        "consent_version": consent.consent_version,
        "speech_provider_processing_allowed": bool(consent.speech_provider_processing_allowed),
        "evaluation_use_allowed": bool(consent.evaluation_use_allowed),
        "audio_retention_allowed": bool(consent.audio_retention_allowed),
        "consented_at": consent.consented_at.isoformat() if consent.consented_at else None,
        "revoked_at": consent.revoked_at.isoformat() if consent.revoked_at else None,
        "is_active": consent.is_active,
    }


__all__ = [
    "give_consent", "revoke_consent", "get_active_consent",
    "require_consent", "retention_allowed", "ConsentError", "CONSENT_VERSION",
]
