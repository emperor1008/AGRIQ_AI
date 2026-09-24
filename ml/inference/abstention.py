"""Abstention policy (Phase 4).

Abstention is a *correct outcome*, not a failure. The predictor refuses to
classify when evidence is insufficient, and the abstention reason is always
recorded. Thresholds come from the model registry (validated values only) —
this module never invents a threshold.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .quality import QualityResult


@dataclass
class AbstentionDecision:
    abstained: bool
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"abstained": self.abstained, "reason": self.reason}


def decide(
    *,
    quality: QualityResult,
    crop_supported: bool,
    expected_crop: str | None,
    detected_crop: str | None,
    predictions: list[dict[str, Any]],
    thresholds: dict[str, Any],
    model_available: bool,
) -> AbstentionDecision:
    """Order matters: structural failures first, then evidence thresholds.

    Thresholds expected in ``thresholds`` (from registry):
      min_probability, margin_ratio, max_top_gap
    All optional — an absent threshold simply skips that check.
    """
    if not model_available:
        return AbstentionDecision(True, "model_unavailable")
    if not crop_supported:
        return AbstentionDecision(True, "crop_not_supported")
    if expected_crop and detected_crop and expected_crop != detected_crop:
        return AbstentionDecision(True, "crop_mismatch")
    if not quality.accepted:
        return AbstentionDecision(True, "image_quality_insufficient")
    if not predictions:
        return AbstentionDecision(True, "no_predictions")

    top = predictions[0]
    prob = float(top["probability"])

    min_prob = thresholds.get("min_probability")
    if min_prob is not None and prob < float(min_prob):
        return AbstentionDecision(True, "low_confidence")

    margin = thresholds.get("margin_ratio")
    if margin is not None and len(predictions) > 1:
        second = float(predictions[1]["probability"])
        if second > 0 and (prob - second) / prob < float(margin):
            return AbstentionDecision(True, "top_predictions_too_close")

    max_gap = thresholds.get("max_top_gap")
    if max_gap is not None and prob < 1.0 and (1.0 - prob) > float(max_gap):
        return AbstentionDecision(True, "outside_training_distribution")

    return AbstentionDecision(False)
