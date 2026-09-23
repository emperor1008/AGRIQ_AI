"""Robustness evaluation (Phase 4).

Measures model stability under **real, recorded perturbations** applied to
real evaluation images (brightness shift, small rotations, compression).
Results are computed from actual runs — nothing is simulated here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageEnhance


def perturbations() -> dict[str, Callable[[Image.Image], Image.Image]]:
    """Documented perturbation set applied during robustness sweeps."""
    return {
        "brightness_+20pct": lambda img: ImageEnhance.Brightness(img).enhance(1.2),
        "brightness_-20pct": lambda img: ImageEnhance.Brightness(img).enhance(0.8),
        "rotate_5deg": lambda img: img.rotate(5, resample=Image.BILINEAR),
        "jpeg_q70": lambda img: _roundtrip_jpeg(img, 70),
        "downscale_75pct": lambda img: img.resize(
            (max(1, int(img.width * 0.75)), max(1, int(img.height * 0.75)))
        ),
    }


def _roundtrip_jpeg(img: Image.Image, quality: int) -> Image.Image:
    import io

    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer).convert(img.mode)


def sweep(predict_fn: Callable[[Image.Image], str], image_paths: list[Path]) -> dict[str, Any]:
    """Run every perturbation over the given images with a predict callable.

    ``predict_fn`` must be the real model pipeline. Results record per-
    perturbation prediction-flip rates — computed, never assumed.
    """
    if not image_paths:
        raise ValueError("Robustness sweep requires real images")
    results: dict[str, Any] = {}
    for name, perturb in perturbations().items():
        flips = 0
        total = 0
        for path in image_paths:
            with Image.open(path) as img:
                baseline = predict_fn(img.copy())
                perturbed = predict_fn(perturb(img.copy()))
            total += 1
            flips += baseline != perturbed
        results[name] = {"n": total, "prediction_flips": flips, "flip_rate": round(flips / total, 4)}
    return results
