"""Image quality gate (Phase 4).

Pre-classification validation with **actionable retake guidance**. A rejected
image never receives disease confidence — the gate result is final for the
request. All checks inspect actually-decoded pixels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from ml.data.image_checks import image_statistics, is_blurry, is_dark, is_overexposed

# Documented, configurable thresholds (mirrors ml/configs/*.yaml defaults).
DEFAULTS = {
    "min_dimension": 200,
    "max_dimension": 6000,
    "min_brightness": 35.0,
    "max_brightness": 232.0,
    "min_blur_score": 12.0,
    "max_file_bytes": 5 * 1024 * 1024,
}

RETAKE_GUIDANCE = {
    "too_small": "Move closer to the affected leaf so it fills more of the photo.",
    "too_dark": "Use natural daylight; avoid shooting in deep shade or at night.",
    "overexposed": "Avoid direct sunlight on the leaf; stand so your shadow falls on it.",
    "blurry": "Hold the phone steady and tap the leaf to focus before taking the photo.",
    "low_leaf_signal": "Move closer and include both healthy and affected leaf portions.",
}


@dataclass
class QualityResult:
    accepted: bool
    issues: list[str] = field(default_factory=list)
    guidance: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "issues": self.issues,
            "guidance": self.guidance,
            "metrics": self.metrics,
        }


def check_image(img: Image.Image, file_bytes: int | None = None, thresholds: dict[str, Any] | None = None) -> QualityResult:
    """Run every quality check; collect all issues (farmer sees them at once)."""
    limits = {**DEFAULTS, **(thresholds or {})}
    issues: list[str] = []
    metrics: dict[str, Any] = {}

    if file_bytes is not None and file_bytes > limits["max_file_bytes"]:
        issues.append("file_too_large")
    if max(img.size) < limits["min_dimension"]:
        issues.append("too_small")
    if min(img.size) > limits["max_dimension"]:
        issues.append("too_large")

    stats = image_statistics(img)
    metrics.update(stats)

    if stats["mean_brightness"] < limits["min_brightness"]:
        issues.append("too_dark")
    if stats["mean_brightness"] > limits["max_brightness"]:
        issues.append("overexposed")
    if is_blurry(img, threshold=float(limits["min_blur_score"])):
        issues.append("blurry")

    # Green-dominance proxy for "contains plant material": mean(G) vs mean(R).
    rgb = img.convert("RGB").resize((64, 64))
    px = list(rgb.getdata())
    mean_r = sum(p[0] for p in px) / len(px)
    mean_g = sum(p[1] for p in px) / len(px)
    mean_b = sum(p[2] for p in px) / len(px)
    metrics["rgb_means"] = {"r": round(mean_r, 1), "g": round(mean_g, 1), "b": round(mean_b, 1)}
    if mean_g <= mean_r or mean_g <= mean_b:
        # Weak signal — likely a document, screenshot or non-plant photo.
        issues.append("low_leaf_signal")

    guidance = list(dict.fromkeys(RETAKE_GUIDANCE[i] for i in issues if i in RETAKE_GUIDANCE))
    return QualityResult(accepted=not issues, issues=issues, guidance=guidance, metrics=metrics)
