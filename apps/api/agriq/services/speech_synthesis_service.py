"""Speech synthesis service (Phase 3) — facade over the voice orchestrator.

Exposes the TTS operation (owner-checked, farmer-facing text only) and the
capability lookup used by the API layer.
"""
from __future__ import annotations

from typing import Any

from ..core.config import BaseConfig
from . import voice_orchestrator


def synthesise(user_id: int, message_ref: str, language_code: str,
               config: BaseConfig) -> dict[str, Any]:
    """Synthesise an owned assistant message in the selected language."""
    return voice_orchestrator.synthesise_message(user_id, message_ref, language_code, config)


def capabilities(config: BaseConfig) -> dict[str, Any]:
    return voice_orchestrator.capabilities(config)


__all__ = ["synthesise", "capabilities"]
