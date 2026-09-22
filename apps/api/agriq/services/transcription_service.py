"""Transcription service (Phase 3) — thin facade over the voice orchestrator.

Keeps the orchestrator's public surface small; exposes the ASR operation and
its result-shaping helpers for tests and future background processing.
"""
from __future__ import annotations

from typing import Any

from ..core.config import BaseConfig
from . import voice_orchestrator


def transcribe(user_ref: str | int, user_id: int, config: BaseConfig) -> dict[str, Any]:
    """ASR for one owned voice session (never fabricates a transcript)."""
    return voice_orchestrator.transcribe_session(user_ref, user_id, config)


__all__ = ["transcribe"]
