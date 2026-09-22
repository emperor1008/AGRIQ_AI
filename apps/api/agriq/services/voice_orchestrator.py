"""Voice orchestrator (Phase 3).

Owns the voice pipeline end-to-end while delegating all agronomy to the
existing Phase 2 copilot:

    consent gate → session → audio validation/storage → ASR provider
    → transcript (raw, confidence verbatim from provider) → farmer review
    → confirmation → EXISTING copilot_orchestrator.run_copilot
    → TTS provider → answer audio

Voice is an interface, not a separate assistant: no agricultural logic
lives here. Key honesty rules:
- A transcript is never fabricated: ASR failure returns an explicit
  unavailable state and the session keeps the text fallback.
- Provider confidence is stored verbatim; absent confidence stays null
  ("Confidence not provided." in the UI). No length-based guessing.
- The copilot is only called with a farmer-confirmed transcript.
- Provider/model identity is recorded on the session and audio rows.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from ..core.config import BaseConfig
from ..core.exceptions import ValidationError
from ..core.logging import get_logger
from ..core.time import utc_now
from ..integrations.speech.provider import TranscriptionResult
from ..repositories.voice_repository import (
    SynthesisedAudioRepository,
    TranscriptRepository,
    VoiceSessionRepository,
)
from . import audio_validation_service
from . import language_service
from . import voice_consent_service
from .agricultural_vocabulary import suggest_correction

logger = get_logger("services.voice")

VOICE_SESSION_TTL_HOURS = 24
#: Circuit breaker: consecutive ASR failures before forced cool-down.
ASR_FAILURE_TRIP_LIMIT = 3

# Simple process-level circuit breaker state (single-process deployments;
# production Redis state comes with the same interface).
_breaker = {"consecutive_failures": 0, "open_until": None}


def _breaker_open() -> bool:
    until = _breaker.get("open_until")
    return bool(until and utc_now() < until)


def _record_asr_success() -> None:
    _breaker["consecutive_failures"] = 0
    _breaker["open_until"] = None


def _record_asr_failure() -> None:
    _breaker["consecutive_failures"] = int(_breaker.get("consecutive_failures", 0)) + 1
    if _breaker["consecutive_failures"] >= ASR_FAILURE_TRIP_LIMIT:
        _breaker["open_until"] = utc_now() + timedelta(minutes=2)
        logger.warning("voice_asr_breaker_open failures=%s", _breaker["consecutive_failures"])


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

def get_asr_providers(config: BaseConfig) -> list[Any]:
    """Configured ASR providers in policy evaluation order."""
    from ..integrations.speech.bhashini_asr import BhashiniASRProvider
    from ..integrations.speech.indian_english_asr import IndianEnglishASRProvider
    from ..integrations.speech.indicconformer_asr import IndicConformerASRProvider

    providers: list[Any] = []
    chosen = (config.get("VOICE_ASR_PROVIDER") or "").strip().lower()
    candidates = [
        BhashiniASRProvider(
            api_key=config.get("BHASHINI_API_KEY", ""),
            user_id=config.get("BHASHINI_USER_ID", ""),
            pipeline_id=config.get("BHASHINI_PIPELINE_ID", ""),
            base_url=config.get("BHASHINI_BASE_URL", ""),
            timeout_seconds=int(config.get("VOICE_PROVIDER_TIMEOUT_SECONDS", 30)),
        ),
        IndicConformerASRProvider(timeout_seconds=int(config.get("VOICE_PROVIDER_TIMEOUT_SECONDS", 60))),
        IndianEnglishASRProvider(timeout_seconds=int(config.get("VOICE_PROVIDER_TIMEOUT_SECONDS", 60))),
    ]
    if chosen:
        # Policy pin: only the configured provider is used (no silent switching).
        name_map = {"bhashini": 0, "indicconformer": 1, "indian_english": 2}
        index = name_map.get(chosen)
        candidates = [candidates[index]] if index is not None else []
    for provider in candidates:
        if provider.is_configured():
            providers.append(provider)
    return providers


def get_tts_providers(config: BaseConfig) -> list[Any]:
    from ..integrations.tts.bhashini_tts import BhashiniTTSProvider
    from ..integrations.tts.device_tts import DeviceTTSProvider
    from ..integrations.tts.indic_tts import IndicTTSProvider

    chosen = (config.get("VOICE_TTS_PROVIDER") or "").strip().lower()
    candidates = [
        BhashiniTTSProvider(
            api_key=config.get("BHASHINI_API_KEY", ""),
            user_id=config.get("BHASHINI_USER_ID", ""),
            pipeline_id=config.get("BHASHINI_PIPELINE_ID", ""),
            base_url=config.get("BHASHINI_BASE_URL", ""),
            timeout_seconds=int(config.get("VOICE_PROVIDER_TIMEOUT_SECONDS", 30)),
        ),
        IndicTTSProvider(timeout_seconds=int(config.get("VOICE_PROVIDER_TIMEOUT_SECONDS", 60))),
    ]
    if chosen:
        name_map = {"bhashini": 0, "indic": 1, "indic_tts": 1}
        index = name_map.get(chosen)
        candidates = [candidates[index]] if index is not None else []
    # Only real server-side synthesis providers count for tts_available.
    # The device voice is a browser fallback surfaced separately in metadata.
    providers = [p for p in candidates if p.is_configured()]
    if chosen == "device":
        providers.append(DeviceTTSProvider())   # metadata-only listing
    return providers


def capabilities(config: BaseConfig) -> dict[str, Any]:
    """Real per-language capability map (never hardcoded to true)."""
    languages: dict[str, dict[str, bool]] = {}
    asr = get_asr_providers(config)
    tts = get_tts_providers(config)
    for code in language_service.SUPPORTED:
        languages[code] = {
            "asr_available": any(p.supports_language(code) for p in asr),
            "tts_available": any(p.supports_language(code) for p in tts),
        }
    return {
        "languages": languages,
        "asr_providers": [p.provider_metadata() for p in asr],
        "tts_providers": [p.provider_metadata() for p in tts],
        "text_input_available": True,   # always — the permanent fallback
    }


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def start_session(user_id: int, data: dict[str, Any], config: BaseConfig) -> dict[str, Any]:
    """Create a voice session (consent-gated, ownership-verified ids)."""
    consent = voice_consent_service.require_consent(user_id)
    language = language_service.language_or_error(data.get("language"))
    retain = voice_consent_service.retention_allowed(consent, bool(data.get("retain_audio", False)))
    session = VoiceSessionRepository.create(user_id, {
        "language_requested": language.code,
        "field_id": data.get("field_id"),
        "crop_cycle_id": data.get("crop_cycle_id"),
        "status": "created",
        "audio_retained": retain,
        "expires_at": utc_now() + timedelta(hours=VOICE_SESSION_TTL_HOURS),
    })
    logger.info("voice_session_started user_id=%s session=%s lang=%s",
                user_id, session.uuid, language.code)
    return _session_dict(session)


def upload_audio(user_ref: str | int, user_id: int, storage: Any,
                 config: BaseConfig) -> dict[str, Any]:
    """Validate + store audio for an owned session (status → uploaded).

    Ownership is verified BEFORE the consent gate so a foreign session is
    indistinguishable from a missing one (404) — never a consent error that
    would reveal session state to a stranger.
    """
    session = _owned_session(user_ref, user_id)
    voice_consent_service.require_consent(user_id)
    if session.status not in (session.STATUS_CREATED, session.STATUS_UPLOADED):
        raise ValidationError("This voice session cannot accept audio anymore.")
    key, info = audio_validation_service.store_audio(user_id, storage, config)
    session = VoiceSessionRepository.update(session, {
        "audio_storage_key": key,
        "audio_format": info.format,
        "actual_duration_seconds": info.duration_seconds,
        "status": session.STATUS_UPLOADED,
    })
    return {"session": _session_dict(session), "audio": info.to_dict()}


def transcribe_session(user_ref: str | int, user_id: int, config: BaseConfig) -> dict[str, Any]:
    """Run ASR on an owned session's audio. Never fabricates a transcript."""
    session = _owned_session(user_ref, user_id)
    if session.status not in (session.STATUS_UPLOADED, session.STATUS_PROCESSING,
                              session.STATUS_FAILED):
        raise ValidationError("This session has no recording ready for transcription.")
    if not session.audio_storage_key:
        raise ValidationError("No recording has been uploaded for this session.")
    if _breaker_open():
        return _transcription_unavailable(session, "circuit_breaker",
                                          "The speech service is temporarily busy. Please try again shortly.")

    providers = get_asr_providers(config)
    if not providers:
        return _transcription_unavailable(
            session, "not_configured",
            "Speech recognition is not available right now. Please type your question.",
        )

    language = session.language_requested
    audio = _load_audio(config, session.audio_storage_key)
    if audio is None:
        return _transcription_unavailable(session, "audio_missing",
                                          "The recording could not be read. Please record again.")

    session = VoiceSessionRepository.update(session, {"status": session.STATUS_PROCESSING})
    for provider in providers:
        if not provider.supports_language(language):
            continue
        result: TranscriptionResult = provider.transcribe(audio, language)
        if result.status == "completed" and result.transcript:
            _record_asr_success()
            transcript = TranscriptRepository.create_for_session(session.id, {
                "raw_transcript": result.transcript,
                "confidence_available": bool(result.confidence.get("available")),
                "provider_confidence": result.confidence.get("value"),
                "confidence_source": result.confidence.get("source"),
                "language_detected": result.language_detected,
            })
            session = VoiceSessionRepository.update(session, {
                "status": session.STATUS_TRANSCRIPT_READY,
                "provider": result.provider,
                "provider_model": result.model,
                "language_detected": result.language_detected,
            })
            payload = _session_dict(session)
            payload["transcript"] = _transcript_dict(transcript)
            return payload
        _record_asr_failure()
        logger.warning("voice_asr_provider_failed provider=%s category=%s",
                       result.provider, result.error_category)
        # Policy pin (VOICE_ASR_PROVIDER) forbids fallback; multi-provider
        # order is only used when no pin is configured.
        if config.get("VOICE_ASR_PROVIDER"):
            break

    return _transcription_unavailable(
        session, "asr_failed",
        "We could not reliably understand this recording. Please try again or type your question.",
    )


def _transcription_unavailable(session, category: str, message: str) -> dict[str, Any]:
    session = VoiceSessionRepository.update(session, {
        "status": session.STATUS_FAILED,
        "failure_reason": category,
    })
    return {
        "session": _session_dict(session),
        "status": "unavailable",
        "error_category": category,
        "message": message,
        "text_fallback_available": True,
    }


def confirm_transcript(user_ref: str | int, user_id: int,
                       confirmed_text: str, language: str | None) -> dict[str, Any]:
    """Store the farmer-confirmed transcript (required before the copilot)."""
    session = _owned_session(user_ref, user_id)
    if session.status not in (session.STATUS_TRANSCRIPT_READY, session.STATUS_TRANSCRIPT_CONFIRMED):
        raise ValidationError(
            "Confirm a transcript before asking the assistant. Record again or type your question."
        )
    text = (confirmed_text or "").strip()
    if not text:
        raise ValidationError("The confirmed transcript cannot be empty.")
    transcript = TranscriptRepository.latest_for_session(session.id)
    if transcript is None:
        raise ValidationError("No transcript exists for this session.")
    from ..core.time import utc_now as _now

    transcript.corrected_transcript = text[:2000]
    transcript.correction_confirmed_at = _now()
    db_commit()
    chosen_language = language_service.normalise(language or session.language_requested)
    session = VoiceSessionRepository.update(session, {
        "status": session.STATUS_TRANSCRIPT_CONFIRMED,
        "language_requested": chosen_language,
    })
    payload = _session_dict(session)
    payload["transcript"] = _transcript_dict(transcript)
    return payload


def ask_copilot(user_ref: str | int, user_id: int, config: BaseConfig) -> dict[str, Any]:
    """Hand the CONFIRMED transcript to the existing Phase 2 copilot."""
    session = _owned_session(user_ref, user_id)
    if session.status != session.STATUS_TRANSCRIPT_CONFIRMED:
        raise ValidationError("Confirm the transcript first, then ask the assistant.")
    transcript = TranscriptRepository.latest_for_session(session.id)
    if transcript is None or not transcript.corrected_transcript:
        raise ValidationError("No confirmed transcript exists for this session.")

    # Delegation — the copilot stays the single agronomy brain.
    from . import copilot_orchestrator
    result = copilot_orchestrator.run_copilot(
        user_id=user_id,
        profile_id=user_id,
        question=transcript.corrected_transcript,
        language=session.language_requested,
        field_id=session.field_id,
        crop_cycle_id=session.crop_cycle_id,
        conversation_ref=_conversation_uuid(session),
        response_mode="full",
        config=config,
    )
    if result.get("ok"):
        session = VoiceSessionRepository.update(session, {
            "status": session.STATUS_COPILOT_COMPLETED,
            "completed_at": utc_now(),
        })
    # Transcript correction suggestion (display-only; farmer confirms).
    suggestion = suggest_correction(transcript.corrected_transcript, session.language_requested[:2])
    payload = _session_dict(session)
    payload["copilot"] = result
    payload["vocabulary_suggestion"] = (
        {"suggestion": suggestion.english_equivalent or suggestion.term,
         "matched_term": suggestion.term}
        if suggestion and suggestion.english_equivalent
        and suggestion.english_equivalent.lower() not in transcript.corrected_transcript.lower()
        else None
    )
    return payload


def synthesise_message(user_id: int, message_ref: str, language_code: str,
                       config: BaseConfig) -> dict[str, Any]:
    """TTS for an owned copilot answer message. Only farmer-facing text."""
    from ..repositories.copilot_repository import ConversationRepository

    message = _owned_message(message_ref, user_id)
    if message is None or message.role != "assistant":
        raise ValidationError("Only assistant answers can be read aloud.")
    language = language_service.language_or_error(language_code)

    # Clean speakable text: the answer only — never JSON, formulas, URLs.
    speakable = _speakable_text(message.content)
    if not speakable:
        raise ValidationError("There is no readable answer text for this message.")

    providers = [p for p in get_tts_providers(config) if p.supports_language(language.code)]
    if not providers:
        return {
            "status": "unavailable",
            "message": "Audio playback is currently unavailable.",
            "text_still_visible": True,
        }

    provider = providers[0]
    result = provider.synthesise(speakable, language.code)
    if result.status != "completed" or not result.audio:
        return {
            "status": "unavailable",
            "message": "Audio playback is currently unavailable.",
            "error_category": result.error_category,
            "text_still_visible": True,
        }

    storage_key, measured_duration = _store_synthesised(
        config, user_id, result.audio, result.audio_format)
    audio_row = SynthesisedAudioRepository.create(user_id, {
        "message_id": message.id,
        "language": language.code,
        "provider": result.provider,
        "provider_model": result.model,
        "storage_key": storage_key,
        "format": result.audio_format,
        "actual_duration_seconds": measured_duration or result.duration_seconds,
        "expires_at": utc_now() + timedelta(hours=VOICE_SESSION_TTL_HOURS),
    })
    return {
        "status": "completed",
        "audio_id": audio_row.uuid,
        "provider": result.provider,
        "model": result.model,
        "audio_format": result.audio_format,
        "duration_seconds": audio_row.actual_duration_seconds,
        "language": language.code,
    }


def delete_recording(user_ref: str | int, user_id: int, config: BaseConfig) -> dict[str, Any]:
    """Delete stored audio immediately (consent/retention control)."""
    session = _owned_session(user_ref, user_id)
    if session.audio_storage_key:
        audio_validation_service.delete_audio(config, session.audio_storage_key)
    session = VoiceSessionRepository.update(session, {
        "audio_storage_key": None,
        "status": (session.STATUS_DELETED if session.status == session.STATUS_CREATED
                   else session.status),
    })
    return {"session": _session_dict(session), "deleted": True}


def cleanup_expired(config: BaseConfig) -> int:
    """Sweep expired sessions and their audio files."""
    from ..repositories.voice_repository import VoiceSessionRepository as VSR
    expired = VSR.mark_expired_sessions(utc_now())
    return expired


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _owned_session(user_ref: str | int, user_id: int):
    session = VoiceSessionRepository.get_owned(user_ref, user_id)
    if session is None:
        from ..core.exceptions import NotFoundError
        raise NotFoundError()
    return session


def _owned_message(message_ref: str, user_id: int):
    from ..repositories.copilot_repository import ConversationRepository

    message = ConversationRepository.get_message(_int_or_none(message_ref))
    if message is None:
        return None
    conversation = message.conversation
    if conversation is None or conversation.user_id != user_id:
        return None
    return message


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _conversation_uuid(session) -> str | None:
    conversation = session.conversation
    if conversation is None:
        return None
    return conversation.uuid or str(conversation.id)


def _load_audio(config: BaseConfig, storage_key: str) -> bytes | None:
    from pathlib import Path

    root = Path(config.get("VOICE_TEMP_STORAGE_PATH") or "voice_audio")
    target = root / storage_key
    try:
        return target.read_bytes()
    except OSError:
        return None


def _speakable_text(content: str) -> str:
    """Answer text only — strips URLs and hard truncates for TTS."""
    import re
    text = re.sub(r"https?://\S+", "", content or "")
    return text.strip()[:2000]


def _store_synthesised(config: BaseConfig, user_id: int, audio: bytes,
                       audio_format: str) -> tuple[str, float | None]:
    import uuid as _uuid
    from pathlib import Path

    root = Path(config.get("VOICE_TEMP_STORAGE_PATH") or "voice_audio")
    target_dir = root / "tts" / str(user_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    ext = "wav" if "wav" in (audio_format or "") else "mp3"
    key = f"tts/{user_id}/{_uuid.uuid4().hex}.{ext}"
    (root / key).write_bytes(audio)
    duration = audio_validation_service.measure_wav(audio)[0] \
        if (audio_format or "").endswith("wav") and audio[:4] == b"RIFF" else None
    return key, duration


def _session_dict(session) -> dict[str, Any]:
    return {
        "session_id": session.uuid or str(session.id),
        "status": session.status,
        "language_requested": session.language_requested,
        "language_detected": session.language_detected,
        "provider": session.provider,
        "provider_model": session.provider_model,
        "audio_retained": bool(session.audio_retained),
        "audio_format": session.audio_format,
        "actual_duration_seconds": session.actual_duration_seconds,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "expires_at": session.expires_at.isoformat() if session.expires_at else None,
    }


def _transcript_dict(transcript) -> dict[str, Any]:
    return {
        "transcript_id": transcript.uuid or str(transcript.id),
        "raw_transcript": transcript.raw_transcript,
        "corrected_transcript": transcript.corrected_transcript,
        "confidence": {
            "available": bool(transcript.confidence_available),
            "value": transcript.provider_confidence if transcript.confidence_available else None,
            "source": transcript.confidence_source if transcript.confidence_available else None,
        },
        "language_detected": transcript.language_detected,
        "confirmed_at": transcript.correction_confirmed_at.isoformat()
        if transcript.correction_confirmed_at else None,
    }


def db_commit() -> None:
    from ..extensions import db
    db.session.commit()


__all__ = [
    "start_session", "upload_audio", "transcribe_session", "confirm_transcript",
    "ask_copilot", "synthesise_message", "delete_recording", "capabilities",
    "cleanup_expired", "get_asr_providers", "get_tts_providers",
    "ASR_FAILURE_TRIP_LIMIT",
]
