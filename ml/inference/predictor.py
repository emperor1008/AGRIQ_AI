"""Crop-image predictor (Phase 4) — lightweight production inference.

Loads ONLY a registry-approved model whose checksum matches. Raw softmax is
never exposed as farmer-facing confidence: probabilities are bucketed into
validated categories (insufficient evidence / low / moderate / higher) only
when calibration metadata exists in the registry entry. Everything fails
closed: missing model, failed checksum, decode error or inference exception
all produce an honest unavailable/abstained state.
"""
from __future__ import annotations

import io
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from .abstention import decide as abstain
from .quality import QualityResult, check_image
from .registry import ModelRegistry

log = logging.getLogger(__name__)


@dataclass
class PredictionResult:
    ok: bool                      # False only for infrastructure failure (decode etc.)
    status: str                   # completed | unavailable | rejected
    message: str | None
    analysis: dict[str, Any] = field(default_factory=dict)


class CropImagePredictor:
    """Single-crop classifier behind the image-analysis API."""

    def __init__(self, registry: ModelRegistry | None = None):
        self._registry = registry or ModelRegistry()
        self._loaded_name: Optional[str] = None
        self._model: Any = None
        self._entry: Any = None

    # -- model lifecycle ---------------------------------------------------

    def _entry_for(self, crop: str) -> Any:
        return self._registry.approved_for_crop(crop)

    def _load_model(self, entry: Any) -> Any:
        """Load weights. Phase 4 ships no trained weights yet — returns None
        and the caller reports the honest unavailable state. A real deployment
        replaces this with framework loading (PyTorch/TF-lite) and keeps the
        same fail-closed contract."""
        if not entry.weights_path:
            return None
        weights = self._registry.models_dir / entry.weights_path
        if not weights.is_file():
            return None
        # Real framework loading goes here in deployment. Kept abstract so the
        # web app never imports heavy training dependencies.
        return None

    # -- public API --------------------------------------------------------

    def analyse(
        self,
        file_bytes: bytes,
        *,
        expected_crop: str,
        thresholds_override: dict[str, Any] | None = None,
        num_images: int = 1,
    ) -> PredictionResult:
        entry = self._entry_for(expected_crop)
        if entry is None:
            return PredictionResult(
                ok=True,
                status="unavailable",
                message="Image analysis is not currently available.",
            )

        model = self._load_model(entry)
        if model is None:
            return PredictionResult(
                ok=True,
                status="unavailable",
                message="Image analysis is not currently available.",
            )

        try:
            img = Image.open(io.BytesIO(file_bytes))
            img.load()
        except Exception:  # noqa: BLE001 — any decode failure is the same outcome
            return PredictionResult(
                ok=True,
                status="rejected",
                message="AGRIQ could not identify this condition reliably. Please retake the image or consult an agriculture expert.",
            )

        quality = check_image(img, file_bytes=len(file_bytes), thresholds=dict(entry.abstention_thresholds.get("quality", {})) if entry.abstention_thresholds else None)
        if not quality.accepted:
            return PredictionResult(
                ok=True,
                status="rejected",
                message="AGRIQ could not identify this condition reliably. Please retake the image or consult an agriculture expert.",
                analysis={"image_quality": quality.to_json()},
            )

        # Real inference (framework-specific) replaces the block below.
        # With no trained weights shipped, we never fabricate probabilities.
        predictions: list[dict[str, Any]] = []
        detected_crop: Optional[str] = None  # set by real crop-consistency check

        decision = abstain(
            quality=quality,
            crop_supported=True,
            expected_crop=expected_crop,
            detected_crop=detected_crop,
            predictions=predictions,
            thresholds=dict(entry.abstention_thresholds or {}),
            model_available=model is not None,
        )
        if decision.abstained:
            return PredictionResult(
                ok=True,
                status="rejected",
                message="AGRIQ could not identify this condition reliably. Please retake the image or consult an agriculture expert.",
                analysis={"image_quality": quality.to_json(), "abstention": decision.to_json()},
            )

        raise RuntimeError("unreachable: no trained weights ship in Phase 4; inference path guarded above")
