"""AI4Bharat IndicConformer ASR integration (Phase 3).

A local/on-prem model path: when ``INDICCONFORMER_MODEL_PATH_OR`` /
``INDICCONFORMER_MODEL_PATH_HI`` point at a deployed IndicConformer
checkpoint and the optional inference stack is installed, this provider
runs real inference. Without a deployed model it reports ``not_configured``
honestly — it never fabricates a transcript, and the module documents the
exact model provenance required (AI4Bharat IndicConformer, CC-BY licence,
model card per language).

The heavy model is intentionally NOT downloaded by CI; deployment is a
separate manual step (see docs/VOICE_ARCHITECTURE.md).
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ...core.logging import get_logger
from .provider import TranscriptionResult

logger = get_logger("integrations.indicconformer")

_LANG_MODEL_KEYS = {"or": "INDICCONFORMER_MODEL_PATH_OR", "hi": "INDICCONFORMER_MODEL_PATH_HI"}
_DEFAULT_TIMEOUT = 60


class IndicConformerASRProvider:
    """Local IndicConformer inference for Odia and Hindi."""

    def __init__(self, *, model_paths: dict[str, str] | None = None,
                 timeout_seconds: int = _DEFAULT_TIMEOUT) -> None:
        import os
        self._model_paths = model_paths or {
            lang: os.environ.get(key, "").strip()
            for lang, key in _LANG_MODEL_KEYS.items()
        }
        self._timeout = timeout_seconds
        self._models: dict[str, Any] = {}

    def is_configured(self) -> bool:
        return any(self._model_exists(lang) for lang in self._model_paths)

    def _model_exists(self, language: str) -> bool:
        path = self._model_paths.get(language, "")
        return bool(path) and Path(path).exists()

    def supports_language(self, language_code: str) -> bool:
        return language_code in self._model_paths and self._model_exists(language_code)

    def provider_metadata(self) -> dict[str, Any]:
        return {
            "provider": "indicconformer-asr",
            "configured": self.is_configured(),
            "languages": sorted(
                lang for lang in self._model_paths if self._model_exists(lang)
            ),
            "licence": "AI4Bharat IndicConformer — CC-BY-4.0 (per model card)",
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
                status="unavailable", provider="indicconformer-asr",
                language_requested=language_code,
                error_category="not_configured",
                reason="No IndicConformer model is deployed for this language.",
            )
        try:
            transcript, confidence_value = self._infer(audio, language_code)
        except ImportError:
            logger.warning("indicconformer_inference_stack_missing")
            return TranscriptionResult(
                status="unavailable", provider="indicconformer-asr",
                language_requested=language_code,
                error_category="not_configured",
                reason="The IndicConformer inference stack is not installed.",
            )
        except Exception as exc:  # noqa: BLE001 — model runtime failure
            logger.warning("indicconformer_failed error=%s", type(exc).__name__)
            return TranscriptionResult(
                status="unavailable", provider="indicconformer-asr",
                language_requested=language_code,
                error_category="api_error",
                reason="The local speech model failed to process this audio.",
            )
        if not transcript:
            return TranscriptionResult(
                status="unavailable", provider="indicconformer-asr",
                language_requested=language_code,
                error_category="api_error",
                reason="The speech model returned no transcript.",
            )
        confidence: dict[str, Any] = {"available": False, "value": None, "source": None}
        if confidence_value is not None:
            confidence = {"available": True, "value": float(confidence_value), "source": "provider"}
        return TranscriptionResult(
            status="completed", provider="indicconformer-asr",
            model=f"indicconformer-{language_code}",
            language_requested=language_code, language_detected=language_code,
            transcript=transcript, confidence=confidence,
            processing_started_at=started,
            processing_completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    def _infer(self, audio: bytes, language: str) -> tuple[str, float | None]:
        """Real inference through the deployed model server.

        The deployment contract: a small HTTP model server (e.g. TorchServe/
        FastAPI) listening on the path configured in the environment returns
        ``{"transcript": "...", "confidence": 0.0-1.0 | null}``. Import of the
        client is lazy so the app never hard-depends on the inference stack.
        """
        import requests

        model_path = self._model_paths[language]
        response = requests.post(
            model_path,
            data=audio,
            headers={"Content-Type": "application/octet-stream",
                     "X-Audio-Language": language},
            timeout=self._timeout,
        )
        response.raise_for_status()
        data = response.json()
        transcript = (data.get("transcript") or "").strip()
        confidence = data.get("confidence")
        if confidence is not None and not isinstance(confidence, (int, float)):
            confidence = None
        return transcript, confidence


__all__ = ["IndicConformerASRProvider"]
