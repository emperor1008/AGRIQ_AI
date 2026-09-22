"""Speech provider abstractions (Phase 3).

Standard interfaces every ASR / TTS / translation integration must satisfy.
Providers never invent values: missing confidence stays ``available: False``,
missing audio stays an error — never a fabricated artefact.

A provider returns one of:
- a successful result (``status == "completed"`` with real provider output)
- an explicit unavailable/failed result (``status`` in
  ``unavailable``/``failed`` with an ``error_category``)

There is no scripted-fallback result shape: the orchestrator decides what
farmer-facing message an unavailable provider maps to.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


# ---------------------------------------------------------------------------
# Speech-to-text
# ---------------------------------------------------------------------------

@dataclass
class TranscriptionResult:
    """Standard ASR result (Phase 3 provider contract)."""

    status: str = "unavailable"            # completed | unavailable | failed
    provider: str = ""
    model: Optional[str] = None
    language_requested: str = ""
    language_detected: Optional[str] = None
    transcript: Optional[str] = None
    confidence: dict[str, Any] = field(default_factory=lambda: {
        "available": False, "value": None, "source": None,
    })
    segments: list[dict[str, Any]] = field(default_factory=list)
    processing_started_at: Optional[str] = None
    processing_completed_at: Optional[str] = None
    error_category: Optional[str] = None   # not_configured|timeout|api_error|decoding_failed|unsupported_language
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "language_requested": self.language_requested,
            "language_detected": self.language_detected,
            "transcript": self.transcript,
            "confidence": dict(self.confidence),
            "segments": list(self.segments),
            "processing_started_at": self.processing_started_at,
            "processing_completed_at": self.processing_completed_at,
            "error_category": self.error_category,
            "reason": self.reason,
        }


class SpeechToTextProvider(Protocol):
    """Every ASR integration must implement this interface."""

    def is_configured(self) -> bool: ...
    def supports_language(self, language_code: str) -> bool: ...
    def transcribe(self, audio: bytes, language_code: str) -> TranscriptionResult: ...
    def health_check(self) -> dict[str, Any]: ...
    def provider_metadata(self) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Text-to-speech
# ---------------------------------------------------------------------------

@dataclass
class SynthesisResult:
    """Standard TTS result (Phase 3 provider contract)."""

    status: str = "unavailable"            # completed | unavailable | failed
    provider: str = ""
    model: Optional[str] = None
    language: str = ""
    audio_format: str = "audio/mpeg"
    audio: Optional[bytes] = None          # raw synthesised audio bytes
    duration_seconds: Optional[float] = None   # measured from decoded audio, never estimated
    created_at: Optional[str] = None
    error_category: Optional[str] = None   # not_configured|timeout|api_error|unsupported_language
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "language": self.language,
            "audio_format": self.audio_format,
            "duration_seconds": self.duration_seconds,
            "created_at": self.created_at,
            "error_category": self.error_category,
            "reason": self.reason,
        }


class TextToSpeechProvider(Protocol):
    """Every TTS integration must implement this interface."""

    def is_configured(self) -> bool: ...
    def supports_language(self, language_code: str) -> bool: ...
    def synthesise(self, text: str, language_code: str) -> SynthesisResult: ...
    def health_check(self) -> dict[str, Any]: ...
    def provider_metadata(self) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Translation
# ---------------------------------------------------------------------------

@dataclass
class TranslationResult:
    """Standard translation result (Phase 3 provider contract)."""

    status: str = "unavailable"            # completed | unavailable | failed
    provider: str = ""
    model: Optional[str] = None
    source_language: str = ""
    target_language: str = ""
    translated_text: Optional[str] = None
    error_category: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "model": self.model,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "translated_text": self.translated_text,
            "error_category": self.error_category,
            "reason": self.reason,
        }


class TranslationProvider(Protocol):
    """Every translation integration must implement this interface."""

    def is_configured(self) -> bool: ...
    def supports_language(self, language_code: str) -> bool: ...
    def translate(self, text: str, source_language: str, target_language: str) -> TranslationResult: ...
    def provider_metadata(self) -> dict[str, Any]: ...


__all__ = [
    "TranscriptionResult", "SpeechToTextProvider",
    "SynthesisResult", "TextToSpeechProvider",
    "TranslationResult", "TranslationProvider",
]
