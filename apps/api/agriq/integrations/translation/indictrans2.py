"""AI4Bharat IndicTrans2 integration (Phase 3).

Local model-server contract. Until ``INDICTRANS2_MODEL_ENDPOINT`` is
configured and the model deployed (licence: AI4Bharat non-commercial /
research terms — verify per release), the provider reports
``not_configured``. It is never silently used; the copilot's own
multilingual generation remains the primary translation-free path.
"""
from __future__ import annotations

import os
from typing import Any

import requests

from ...core.logging import get_logger
from ..speech.provider import TranslationResult

logger = get_logger("integrations.indictrans2")

SUPPORTED_LANGUAGES = {"or", "hi", "en"}
_DEFAULT_TIMEOUT = 60


class IndicTrans2Provider:
    """Local IndicTrans2 inference via a deployed model server."""

    def __init__(self, *, endpoint: str | None = None,
                 timeout_seconds: int = _DEFAULT_TIMEOUT) -> None:
        self._endpoint = (endpoint or os.environ.get("INDICTRANS2_MODEL_ENDPOINT", "")).strip()
        self._timeout = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self._endpoint)

    def supports_language(self, language_code: str) -> bool:
        return language_code in SUPPORTED_LANGUAGES and self.is_configured()

    def provider_metadata(self) -> dict[str, Any]:
        return {
            "provider": "indictrans2",
            "configured": self.is_configured(),
            "languages": sorted(SUPPORTED_LANGUAGES),
            "licence": "AI4Bharat IndicTrans2 — verify per-release terms",
            "processing_location": "on-premises (local model server)",
        }

    def translate(self, text: str, source_language: str, target_language: str) -> TranslationResult:
        if not self.is_configured():
            return TranslationResult(
                status="unavailable", provider="indictrans2",
                source_language=source_language, target_language=target_language,
                error_category="not_configured",
                reason="IndicTrans2 is not deployed on this installation.",
            )
        try:
            response = requests.post(
                self._endpoint,
                json={"text": text, "source_language": source_language,
                      "target_language": target_language},
                timeout=self._timeout,
            )
            response.raise_for_status()
            data = response.json()
            translated = (data.get("translation") or "").strip()
        except requests.exceptions.Timeout:
            return TranslationResult(
                status="unavailable", provider="indictrans2",
                source_language=source_language, target_language=target_language,
                error_category="timeout", reason="The translation provider did not respond in time.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("indictrans2_error error=%s", type(exc).__name__)
            return TranslationResult(
                status="unavailable", provider="indictrans2",
                source_language=source_language, target_language=target_language,
                error_category="api_error", reason="The translation provider returned an error.",
            )
        if not translated:
            return TranslationResult(
                status="unavailable", provider="indictrans2",
                source_language=source_language, target_language=target_language,
                error_category="api_error", reason="The translation provider returned no text.",
            )
        return TranslationResult(
            status="completed", provider="indictrans2", model="indictrans2",
            source_language=source_language, target_language=target_language,
            translated_text=translated,
        )


__all__ = ["IndicTrans2Provider", "SUPPORTED_LANGUAGES"]
