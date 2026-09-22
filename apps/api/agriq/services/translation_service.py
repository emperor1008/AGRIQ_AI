"""Translation service (Phase 3).

Auxiliary display-support translation via the configured provider. The
copilot's own multilingual generation is the primary path; this service is
for optional summaries only and never touches chemical names, varieties or
units blindly (callers must pass agricultural-term text through
agricultural_vocabulary checks first).
"""
from __future__ import annotations

from typing import Any

from ..core.config import BaseConfig
from ..integrations.speech.provider import TranslationResult
from ..integrations.translation.bhashini_translation import BhashiniTranslationProvider
from ..integrations.translation.indictrans2 import IndicTrans2Provider


def get_translation_providers(config: BaseConfig) -> list[Any]:
    candidates = [
        BhashiniTranslationProvider(
            api_key=config.get("BHASHINI_API_KEY", ""),
            user_id=config.get("BHASHINI_USER_ID", ""),
            pipeline_id=config.get("BHASHINI_PIPELINE_ID", ""),
            base_url=config.get("BHASHINI_BASE_URL", ""),
            timeout_seconds=int(config.get("VOICE_PROVIDER_TIMEOUT_SECONDS", 30)),
        ),
        IndicTrans2Provider(timeout_seconds=int(config.get("VOICE_PROVIDER_TIMEOUT_SECONDS", 60))),
    ]
    chosen = (config.get("VOICE_TRANSLATION_PROVIDER") or "").strip().lower()
    if chosen:
        name_map = {"bhashini": 0, "indictrans2": 1}
        index = name_map.get(chosen)
        candidates = [candidates[index]] if index is not None else []
    return [p for p in candidates if p.is_configured()]


def translate(text: str, source_language: str, target_language: str,
              config: BaseConfig) -> TranslationResult:
    """Translate via the first configured provider, or unavailable."""
    for provider in get_translation_providers(config):
        if provider.supports_language(source_language) and provider.supports_language(target_language):
            return provider.translate(text, source_language, target_language)
    return TranslationResult(
        status="unavailable", provider="none",
        source_language=source_language, target_language=target_language,
        error_category="not_configured",
        reason="No translation provider is configured on this deployment.",
    )


__all__ = ["translate", "get_translation_providers"]
