"""Image validation utilities (Phase 4).

Pure-function checks used by both the ingestion pipeline and the inference
quality gate. Uses Pillow only — no fabricated measurements, every check
inspects actually-decoded pixels.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

# Decompression-bomb protection: refuse absurdly large declared sizes.
MAX_DECLARED_PIXELS = 100_000_000  # 100 MP
# Inference/ingestion working size limits.
MAX_DIMENSION = 8_000
MIN_DIMENSION = 32

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Streaming SHA-256 of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def decode_verified(path: Path) -> Image.Image:
    """Decode an image with decompression-bomb protection and format check.

    Raises ValueError for any unsupported or unsafe image. The check is based
    on the actually-decoded content, never the extension or a MIME header.
    """
    # Guard the declared size before Pillow allocates memory.
    probe = Image.open(path)
    width, height = probe.size
    if width * height > MAX_DECLARED_PIXELS:
        raise ValueError("Image exceeds decompression-bomb pixel limit")
    probe.load()  # force full decode; truncated files raise here
    if probe.format not in ALLOWED_FORMATS:
        raise ValueError(f"Unsupported image format: {probe.format!r}")
    if max(width, height) > MAX_DIMENSION or min(width, height) < MIN_DIMENSION:
        raise ValueError(f"Image dimensions out of range: {width}x{height}")
    return probe


def image_statistics(img: Image.Image) -> dict[str, Any]:
    """Real pixel statistics used by quality gates."""
    grey = img.convert("L")
    stat = ImageStat.Stat(grey)
    mean = stat.mean[0]
    stddev = stat.stddev[0]
    return {
        "width": img.width,
        "height": img.height,
        "mean_brightness": round(float(mean), 2),
        "std_brightness": round(float(stddev), 2),
    }


def is_dark(img: Image.Image, threshold: float = 28.0) -> bool:
    return image_statistics(img)["mean_brightness"] < threshold


def is_overexposed(img: Image.Image, threshold: float = 235.0) -> bool:
    return image_statistics(img)["mean_brightness"] > threshold


def is_blurry(img: Image.Image, threshold: float = 12.0) -> bool:
    """Low horizontal-gradient variance indicates blur (Laplacian proxy).

    This is a simple, documented heuristic — not a trained blur detector.
    """
    grey = img.convert("L")
    px = grey.load()
    width, height = grey.size
    if width < 3 or height < 3:
        return True
    total, count = 0.0, 0
    for y in range(1, height - 1, 2):
        previous = px[0, y]
        for x in range(1, width - 1, 2):
            current = px[x, y]
            total += abs(current - previous)
            previous = current
            count += 1
    if count == 0:
        return True
    return (total / count) < threshold
