"""Bhashini translation integration (Phase 3).

Real HTTP client for the Bhashini translation pipeline when configured.
Used only for display/summary support — never to translate chemical names,
crop varieties or units blindly (the copilot's own multilingual answers are
the primary path; translation is auxiliary).
"""
from __future__ import annotations

from typing import Any

import requests

from ...core.logging import get_logger
from ..speech.provider import TranslationResult

logger = get_logger("integrations.bhashini_translation")

SUPPORTED_LANGUAGES = {"or", "hi", "en"}
_DEFAULT_TIMEOUT = 30


class BhashiniTranslationProvider:
    """Bhashini translation via the ULCA inference API contract."""

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
            "provider": "bhashini-translation",
            "configured": self.is_configured(),
            "languages": sorted(SUPPORTED_LANGUAGES),
            "licence": "Bhashini ULCA service terms (per-deployment agreement)",
            "processing_location": "Bhashini cloud (India)",
        }

    def translate(self, text: str, source_language: str, target_language: str) -> TranslationResult:
        if not self.is_configured():
            return TranslationResult(
                status="unavailable", provider="bhashini-translation",
                source_language=source_language, target_language=target_language,
                error_category="not_configured",
                reason="Bhashini translation is not configured on this deployment.",
            )
        headers = {
            "Authorization": self._api_key, "User-ID": self._user_id,
            "Content-Type": "application/json",
        }
        payload = {
            "pipelineTasks": [{"taskType": "translation", "config": {
                "language": {"sourceLanguage": source_language,
                             "targetLanguage": target_language},
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
            translated = data["pipelineResponse"][0]["output"][0]["target"]
        except requests.exceptions.Timeout:
            return TranslationResult(
                status="unavailable", provider="bhashini-translation",
                source_language=source_language, target_language=target_language,
                error_category="timeout", reason="The translation provider did not respond in time.",
            )
        except (requests.exceptions.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            logger.warning("bhashini_translation_error error=%s", type(exc).__name__)
            return TranslationResult(
                status="unavailable", provider="bhashini-translation",
                source_language=source_language, target_language=target_language,
                error_category="api_error", reason="The translation provider returned an error.",
            )
        if not (translated or "").strip():
            return TranslationResult(
                status="unavailable", provider="bhashini-translation",
                source_language=source_language, target_language=target_language,
                error_category="api_error", reason="The translation provider returned no text.",
            )
        return TranslationResult(
            status="completed", provider="bhashini-translation", model=self._pipeline_id,
            source_language=source_language, target_language=target_language,
            translated_text=translated.strip(),
        )


__all__ = ["BhashiniTranslationProvider", "SUPPORTED_LANGUAGES"]
