"""Indian-English ASR integration (Phase 3).

Contract for a validated Indian-English (`en-IN`) ASR model. The default
deployment binds to a local Whisper-family model fine-tuned/validated on
Indian-accented speech served through the same model-server contract as
IndicConformer. Until ``INDIAN_ENGLISH_ASR_MODEL_PATH`` points at a
deployed, validated model this provider reports ``not_configured`` —
browser speech recognition is never silently substituted (Phase 3 policy).

Important: browser Web Speech API is NOT a server-side provider. It is a
client-side progressive enhancement only; it can never fill this role.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from ...core.logging import get_logger
from .provider import TranscriptionResult

logger = get_logger("integrations.indian_english_asr")

_DEFAULT_TIMEOUT = 60


class IndianEnglishASRProvider:
    """Local validated en-IN model inference (model-server contract)."""

    def __init__(self, *, model_path: str | None = None,
                 timeout_seconds: int = _DEFAULT_TIMEOUT) -> None:
        self._model_path = (model_path or os.environ.get(
            "INDIAN_ENGLISH_ASR_MODEL_PATH", ""
        )).strip()
        self._timeout = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self._model_path) and Path(self._model_path).exists()

    def supports_language(self, language_code: str) -> bool:
        return language_code == "en-IN" and self.is_configured()

    def provider_metadata(self) -> dict[str, Any]:
        return {
            "provider": "indian-english-asr",
            "configured": self.is_configured(),
            "languages": ["en-IN"] if self.is_configured() else [],
            "licence": "Per deployed model card (documented at deployment)",
            "processing_location": "on-premises (local model server)",
        }

    def health_check(self) -> dict[str, Any]:
        if not self.is_configured():
            return {"healthy": False, "reason": "not_configured"}
        return {"healthy": True, "reason": None}

    def transcribe(self, audio: bytes, language_code: str) -> TranscriptionResult:
        started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not self.supports_language(language_code):
            return TranscriptionResult(
                status="unavailable", provider="indian-english-asr",
                language_requested=language_code,
                error_category="not_configured",
                reason="No validated Indian-English ASR model is deployed.",
            )
        try:
            transcript, confidence_value = self._infer(audio)
        except Exception as exc:  # noqa: BLE001 — model runtime failure
            logger.warning("indian_english_asr_failed error=%s", type(exc).__name__)
            return TranscriptionResult(
                status="unavailable", provider="indian-english-asr",
                language_requested=language_code,
                error_category="api_error",
                reason="The local speech model failed to process this audio.",
            )
        if not transcript:
            return TranscriptionResult(
                status="unavailable", provider="indian-english-asr",
                language_requested=language_code,
                error_category="api_error",
                reason="The speech model returned no transcript.",
            )
        confidence: dict[str, Any] = {"available": False, "value": None, "source": None}
        if confidence_value is not None:
            confidence = {"available": True, "value": float(confidence_value), "source": "provider"}
        return TranscriptionResult(
            status="completed", provider="indian-english-asr",
            model="indian-english-asr",
            language_requested=language_code, language_detected="en-IN",
            transcript=transcript, confidence=confidence,
            processing_started_at=started,
            processing_completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    def _infer(self, audio: bytes) -> tuple[str, float | None]:
        """Same model-server contract as IndicConformer (see that module)."""
        import requests

        response = requests.post(
            self._model_path,
            data=audio,
            headers={"Content-Type": "application/octet-stream",
                     "X-Audio-Language": "en-IN"},
            timeout=self._timeout,
        )
        response.raise_for_status()
        data = response.json()
        transcript = (data.get("transcript") or "").strip()
        confidence = data.get("confidence")
        if confidence is not None and not isinstance(confidence, (int, float)):
            confidence = None
        return transcript, confidence


__all__ = ["IndianEnglishASRProvider"]
