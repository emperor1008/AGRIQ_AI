"""AI4Bharat Indic-TTS integration (Phase 3).

Local model-server contract (same deployment shape as the ASR providers):
``INDIC_TTS_MODEL_PATH_{OR,HI,EN}`` point at deployed Indic-TTS endpoints.
Without deployed models the provider reports ``not_configured`` — the
device-native browser voice remains a separately-labelled fallback, never a
silent substitute for a real synthesised answer.
"""
from __future__ import annotations

import os
import time
from typing import Any

from ...core.logging import get_logger
from .provider import SynthesisResult

logger = get_logger("integrations.indic_tts")

_LANG_MODEL_KEYS = {
    "or": "INDIC_TTS_MODEL_PATH_OR",
    "hi": "INDIC_TTS_MODEL_PATH_HI",
    "en-IN": "INDIC_TTS_MODEL_PATH_EN",
}
_DEFAULT_TIMEOUT = 60


class IndicTTSProvider:
    """Local Indic-TTS inference via deployed model servers."""

    def __init__(self, *, model_paths: dict[str, str] | None = None,
                 timeout_seconds: int = _DEFAULT_TIMEOUT) -> None:
        self._model_paths = model_paths or {
            lang: os.environ.get(key, "").strip()
            for lang, key in _LANG_MODEL_KEYS.items()
        }
        self._timeout = timeout_seconds

    def is_configured(self) -> bool:
        return any(self._endpoint_exists(lang) for lang in self._model_paths)

    def _endpoint_exists(self, language: str) -> bool:
        # Endpoints are URLs for the TTS deployment (http/https) or file paths.
        path = self._model_paths.get(language, "")
        return bool(path) and (path.startswith(("http://", "https://")) or os.path.exists(path))

    def supports_language(self, language_code: str) -> bool:
        return language_code in self._model_paths and self._endpoint_exists(language_code)

    def provider_metadata(self) -> dict[str, Any]:
        return {
            "provider": "indic-tts",
            "configured": self.is_configured(),
            "languages": sorted(
                lang for lang in self._model_paths if self._endpoint_exists(lang)
            ),
            "licence": "AI4Bharat Indic-TTS — CC-BY-4.0 (per model card)",
            "processing_location": "on-premises (local model server)",
        }

    def health_check(self) -> dict[str, Any]:
        if not self.is_configured():
            return {"healthy": False, "reason": "not_configured"}
        return {"healthy": True, "reason": None}

    def synthesise(self, text: str, language_code: str) -> SynthesisResult:
        started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.supports_language(language_code):
            return SynthesisResult(
                status="unavailable", provider="indic-tts", language=language_code,
                error_category="not_configured",
                reason="No Indic-TTS model is deployed for this language.",
            )
        try:
            audio, audio_format = self._synthesise_via_server(text, language_code)
        except Exception as exc:  # noqa: BLE001 — model runtime failure
            logger.warning("indic_tts_failed error=%s", type(exc).__name__)
            return SynthesisResult(
                status="unavailable", provider="indic-tts", language=language_code,
                error_category="api_error",
                reason="The local speech model failed to synthesise audio.",
            )
        if not audio:
            return SynthesisResult(
                status="unavailable", provider="indic-tts", language=language_code,
                error_category="api_error",
                reason="The speech model returned no audio.",
            )
        return SynthesisResult(
            status="completed", provider="indic-tts",
            model=f"indic-tts-{language_code}",
            language=language_code, audio_format=audio_format or "audio/wav",
            audio=audio, duration_seconds=None,  # measured by the service after decode
            created_at=started,
        )

    def _synthesise_via_server(self, text: str, language: str) -> tuple[bytes, str | None]:
        import requests

        response = requests.post(
            self._model_paths[language],
            json={"text": text, "language": language},
            headers={"Accept": "audio/wav"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "audio/wav").split(";")[0]
        return response.content, content_type


__all__ = ["IndicTTSProvider"]
