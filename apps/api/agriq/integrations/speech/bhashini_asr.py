"""Bhashini speech-to-text integration (Phase 3).

Uses the Bhashini (National Language Translation Mission) ASR pipeline when
``BHASHINI_API_KEY`` (+ user id / pipeline id) is configured. This module
implements the real HTTP contract against the Bhashini endpoints; without
credentials ``is_configured()`` is False and the provider reports
``not_configured`` — the orchestrator then reports ASR unavailable honestly.

No retry storms: one bounded attempt with a provider timeout (the voice
orchestrator applies its own circuit breaker across turns).
"""
from __future__ import annotations

import time
from typing import Any

import requests

from ...core.logging import get_logger
from .provider import TranscriptionResult

logger = get_logger("integrations.bhashini_asr")

SUPPORTED_LANGUAGES = {"or", "hi", "en-IN"}
_DEFAULT_TIMEOUT = 30


class BhashiniASRProvider:
    """Bhashini ASR via the ULCA inference API contract."""

    def __init__(self, *, api_key: str = "", user_id: str = "",
                 pipeline_id: str = "", base_url: str = "",
                 timeout_seconds: int = _DEFAULT_TIMEOUT) -> None:
        self._api_key = (api_key or "").strip()
        self._user_id = (user_id or "").strip()
        self._pipeline_id = (pipeline_id or "").strip()
        self._base_url = (base_url or "https://meity-auth.ulcacontrib.org").strip()
        self._timeout = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self._api_key and self._pipeline_id)

    def supports_language(self, language_code: str) -> bool:
        return language_code in SUPPORTED_LANGUAGES

    def provider_metadata(self) -> dict[str, Any]:
        return {
            "provider": "bhashini-asr",
            "configured": self.is_configured(),
            "languages": sorted(SUPPORTED_LANGUAGES),
            "licence": "Bhashini ULCA service terms (per-deployment agreement)",
            "processing_location": "Bhashini cloud (India)",
        }

    def health_check(self) -> dict[str, Any]:
        if not self.is_configured():
            return {"healthy": False, "reason": "not_configured"}
        return {"healthy": True, "reason": None}

    def transcribe(self, audio: bytes, language_code: str) -> TranscriptionResult:
        started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.is_configured():
            return TranscriptionResult(
                status="unavailable", provider="bhashini-asr",
                language_requested=language_code,
                error_category="not_configured",
                reason="Bhashini ASR is not configured on this deployment.",
            )
        if not self.supports_language(language_code):
            return TranscriptionResult(
                status="unavailable", provider="bhashini-asr",
                language_requested=language_code,
                error_category="unsupported_language",
                reason=f"Language {language_code} is not supported by this provider.",
            )

        headers = {
            "Authorization": self._api_key,
            "User-ID": self._user_id,
            "Content-Type": "application/json",
        }
        payload = {
            "pipelineTasks": [{"taskType": "asr", "config": {
                "language": {"sourceLanguage": _bhashini_lang(language_code)},
            }}],
            "audio": [{"audioContent": _b64_audio(audio)}],
        }
        try:
            response = requests.post(
                f"{self._base_url}/ml-inference/v1/compute",
                json=payload, headers=headers, timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.Timeout:
            return _unavailable(language_code, "timeout", "The speech provider did not respond in time.", started)
        except (requests.exceptions.RequestException, ValueError) as exc:
            logger.warning("bhashini_asr_error error=%s", type(exc).__name__)
            return _unavailable(language_code, "api_error", "The speech provider returned an error.", started)

        transcript, confidence, detected = _parse_response(data)
        if transcript is None:
            return _unavailable(language_code, "api_error",
                                "The speech provider returned no transcript.", started)
        return TranscriptionResult(
            status="completed", provider="bhashini-asr", model=self._pipeline_id,
            language_requested=language_code, language_detected=detected or language_code,
            transcript=transcript, confidence=confidence,
            processing_started_at=started,
            processing_completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )


def _unavailable(lang: str, category: str, reason: str, started: str) -> TranscriptionResult:
    return TranscriptionResult(
        status="unavailable", provider="bhashini-asr", language_requested=lang,
        processing_started_at=started,
        processing_completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        error_category=category, reason=reason,
    )


def _bhashini_lang(code: str) -> str:
    return {"en-IN": "en"}.get(code, code)


def _b64_audio(audio: bytes) -> str:
    import base64
    return base64.b64encode(audio).decode("ascii")


def _parse_response(data: dict[str, Any]) -> tuple[Optional[str], dict[str, Any], Optional[str]]:
    """Extract transcript/confidence from the ULCA response shapes."""
    try:
        outputs = data["pipelineResponse"][0]["output"]
        first = outputs[0]
        transcript = (first.get("transcript") or "").strip()
        confidence_raw = first.get("confidence")
        detected = first.get("language", {}).get("sourceLanguage") \
            if isinstance(first.get("language"), dict) else None
    except (KeyError, IndexError, TypeError):
        return None, {"available": False, "value": None, "source": None}, None
    if not transcript:
        return None, {"available": False, "value": None, "source": None}, detected
    confidence: dict[str, Any] = {"available": False, "value": None, "source": None}
    if isinstance(confidence_raw, (int, float)):
        confidence = {"available": True, "value": float(confidence_raw), "source": "provider"}
    return transcript, confidence, detected


__all__ = ["BhashiniASRProvider", "SUPPORTED_LANGUAGES"]
