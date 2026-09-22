"""Bhashini text-to-speech integration (Phase 3).

Real HTTP client for the Bhashini TTS pipeline when configured. Without
credentials it reports ``not_configured``; a failed synthesis never returns
an empty audio file as success.
"""
from __future__ import annotations

import time
from typing import Any

import requests

from ...core.logging import get_logger
from .provider import SynthesisResult

logger = get_logger("integrations.bhashini_tts")

SUPPORTED_LANGUAGES = {"or", "hi", "en-IN"}
_DEFAULT_TIMEOUT = 30


class BhashiniTTSProvider:
    """Bhashini TTS via the ULCA inference API contract."""

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
            "provider": "bhashini-tts",
            "configured": self.is_configured(),
            "languages": sorted(SUPPORTED_LANGUAGES),
            "licence": "Bhashini ULCA service terms (per-deployment agreement)",
            "processing_location": "Bhashini cloud (India)",
        }

    def health_check(self) -> dict[str, Any]:
        if not self.is_configured():
            return {"healthy": False, "reason": "not_configured"}
        return {"healthy": True, "reason": None}

    def synthesise(self, text: str, language_code: str) -> SynthesisResult:
        started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.is_configured():
            return SynthesisResult(
                status="unavailable", provider="bhashini-tts", language=language_code,
                error_category="not_configured",
                reason="Bhashini TTS is not configured on this deployment.",
            )
        if not self.supports_language(language_code):
            return SynthesisResult(
                status="unavailable", provider="bhashini-tts", language=language_code,
                error_category="unsupported_language",
                reason=f"Language {language_code} is not supported by this provider.",
            )
        headers = {
            "Authorization": self._api_key,
            "User-ID": self._user_id,
            "Content-Type": "application/json",
        }
        payload = {
            "pipelineTasks": [{"taskType": "tts", "config": {
                "language": {"sourceLanguage": {"en-IN": "en"}.get(language_code, language_code)},
            }}],
            "input": [{"source": text}],
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
            logger.warning("bhashini_tts_error error=%s", type(exc).__name__)
            return _unavailable(language_code, "api_error", "The speech provider returned an error.", started)

        audio_b64, audio_format = _parse_response(data)
        if not audio_b64:
            return _unavailable(language_code, "api_error",
                                "The speech provider returned no audio.", started)
        import base64
        audio = base64.b64decode(audio_b64)
        return SynthesisResult(
            status="completed", provider="bhashini-tts", model=self._pipeline_id,
            language=language_code, audio_format=audio_format or "audio/wav",
            audio=audio, duration_seconds=_measure_duration(audio, audio_format or "audio/wav"),
            created_at=started,
        )


def _unavailable(lang: str, category: str, reason: str, started: str) -> SynthesisResult:
    return SynthesisResult(
        status="unavailable", provider="bhashini-tts", language=lang,
        created_at=started, error_category=category, reason=reason,
    )


def _parse_response(data: dict[str, Any]) -> tuple[str | None, str | None]:
    try:
        output = data["pipelineResponse"][0]["output"][0]
        audio_b64 = output.get("audioContent")
        audio_format = output.get("audioFormat")
    except (KeyError, IndexError, TypeError):
        return None, None
    return (audio_b64 or None), audio_format


def _measure_duration(audio: bytes, audio_format: str) -> float | None:
    """Actual decoded duration; None when not measurable (never estimated)."""
    try:
        import io
        if audio_format == "audio/wav" or audio[:4] == b"RIFF":
            import wave
            with wave.open(io.BytesIO(audio), "rb") as reader:
                frames = reader.getnframes()
                rate = reader.getframerate()
                if rate:
                    return round(frames / float(rate), 2)
        return None
    except Exception:  # noqa: BLE001 — duration is best-effort metadata
        return None


__all__ = ["BhashiniTTSProvider", "SUPPORTED_LANGUAGES"]
