"""LeafScan service: transparent image screening (ARC-07).

This is a colour-pattern heuristic over the uploaded image using Pillow.
It is explicitly NOT a trained crop-disease model and its output is
presented in the UI as visual symptom *screening*, never diagnosis.

Honest status (Phase 7 §15/§31): the numeric ``confidence`` field is a
**rule-based screening band**, never a calibrated probability. It is always
published with ``confidence_status`` (``PROBABILITY_NOT_CALIBRATED``) and
``confidence_basis``. When the image has too little leaf area to screen, the
result is marked ``IMAGE_ANALYSIS_UNCERTAIN`` rather than forced into a
symptom band. Trained-model inference, with its own approval and calibration
gates, lives in ``ml/inference`` and reports an honest unavailable state until
a model is registered.
"""
from __future__ import annotations

import base64
import colorsys
import io
from typing import Any

from PIL import Image, UnidentifiedImageError

from ..core.constants import (
    ALLOWED_UPLOAD_EXTENSIONS,
    BASIS_IMAGE_COLOUR_HEURISTIC,
    MAX_UPLOAD_BYTES,
    TOKEN_DATA_UNAVAILABLE,
    TOKEN_IMAGE_ANALYSIS_UNCERTAIN,
    TOKEN_PROBABILITY_NOT_CALIBRATED,
)
from ..core.exceptions import InvalidImageError
from ..domain.risk.scoring import clamp

#: (width, height) cap applied before analysis.
THUMBNAIL_SIZE = (440, 440)


def empty_result() -> dict[str, Any]:
    """Result shape used when no usable image is provided."""
    return {
        "available": False,
        "preview": None,
        "symptom": "No image uploaded",
        "confidence": 0,
        "confidence_status": TOKEN_DATA_UNAVAILABLE,
        "confidence_basis": BASIS_IMAGE_COLOUR_HEURISTIC,
        "uncertain": False,
        "green_pct": 0,
        "yellow_pct": 0,
        "brown_pct": 0,
        "dark_pct": 0,
        "evidence_score": 0,
        "explanation": (
            "Risk is calculated using crop, district, growth stage and climate conditions. "
            "Uploading a clear leaf image adds visual symptom evidence."
        ),
        "recommendation": "Upload one clear leaf/crop image with natural light for stronger symptom support.",
    }


def validate_upload(file_storage: Any) -> bytes:
    """Validate type and size before any processing; raise InvalidImageError."""
    if file_storage is None or not getattr(file_storage, "filename", ""):
        raise InvalidImageError()

    filename = (file_storage.filename or "").lower()
    if "." not in filename or filename.rsplit(".", 1)[1] not in ALLOWED_UPLOAD_EXTENSIONS:
        raise InvalidImageError()

    mimetype = (getattr(file_storage, "mimetype", "") or "").lower()
    raw = file_storage.read()
    if not raw:
        raise InvalidImageError()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise InvalidImageError()
    if mimetype and mimetype not in {"", "application/octet-stream"} | set(
        m for m in {"image/jpeg", "image/png", "image/webp"}
    ):
        raise InvalidImageError()
    return raw


def analyze_leaf_image(file_storage: Any) -> dict[str, Any]:
    """Screen an uploaded leaf/crop image for visible colour patterns.

    Raises :class:`InvalidImageError` for missing/oversized/unsupported
    uploads; decoding failures degrade to an honest processing-failure
    result, never a fabricated finding.
    """
    raw = validate_upload(file_storage)

    try:
        image = Image.open(io.BytesIO(raw)).convert("RGB")
    except (UnidentifiedImageError, OSError):
        raise InvalidImageError() from None

    image.thumbnail(THUMBNAIL_SIZE)

    preview_io = io.BytesIO()
    image.save(preview_io, format="JPEG", quality=82)
    preview_b64 = base64.b64encode(preview_io.getvalue()).decode("utf-8")

    pixels = list(image.getdata())
    total = len(pixels) or 1
    green = yellow = brown = dark = leaf_like = 0

    for r, g, b in pixels:
        brightness = (r + g + b) / 765
        if brightness > 0.94 or brightness < 0.04:
            continue
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        hue = h * 360

        if s > 0.16 and v > 0.10:
            leaf_like += 1
        if 65 <= hue <= 170 and s > 0.18 and v > 0.15:
            green += 1
        elif 38 <= hue < 65 and s > 0.16 and v > 0.20:
            yellow += 1
        elif 10 <= hue < 42 and s > 0.20 and 0.10 < v < 0.72:
            brown += 1
        elif v < 0.24 and s > 0.14:
            dark += 1

    if leaf_like < total * 0.06:
        return {
            "available": True,
            "preview": preview_b64,
            "symptom": "Unclear leaf area",
            "confidence": 38,
            # Phase 7 §15: too little leaf area to screen — say so instead of
            # forcing a symptom band.
            "confidence_status": TOKEN_IMAGE_ANALYSIS_UNCERTAIN,
            "confidence_basis": BASIS_IMAGE_COLOUR_HEURISTIC,
            "uncertain": True,
            "green_pct": 0,
            "yellow_pct": 0,
            "brown_pct": 0,
            "dark_pct": 0,
            "evidence_score": 4,
            "explanation": "The uploaded image does not contain enough clear leaf area for strong symptom evidence.",
            "recommendation": "Retake image closer to the leaf with plain background and good natural light.",
        }

    green_pct = round((green / leaf_like) * 100, 1)
    yellow_pct = round((yellow / leaf_like) * 100, 1)
    brown_pct = round((brown / leaf_like) * 100, 1)
    dark_pct = round((dark / leaf_like) * 100, 1)
    lesion = brown_pct + dark_pct
    evidence_score = clamp(int(lesion * 1.25 + yellow_pct * 0.45), 0, 22)

    if lesion >= 14:
        symptom = "Visible lesion / blight-like stress pattern"
        confidence = clamp(58 + int(lesion), 58, 90)
        rec = "Inspect nearby plants, remove heavily infected leaves, improve spacing and drainage, then confirm before chemical treatment."
    elif yellow_pct >= 20:
        symptom = "Yellowing / chlorosis stress pattern"
        confidence = clamp(52 + int(yellow_pct), 52, 86)
        rec = "Check waterlogging, nutrient deficiency, root damage and sucking pests."
    elif green_pct >= 58 and lesion < 8:
        symptom = "No strong visible symptom detected"
        confidence = 70
        rec = "Continue monitoring; avoid unnecessary pesticide use unless field symptoms increase."
    else:
        symptom = "Mixed early stress signal"
        confidence = 60
        rec = "Use this as an early warning and confirm with field scouting."

    return {
        "available": True,
        "preview": preview_b64,
        "symptom": symptom,
        "confidence": int(confidence),
        "confidence_status": TOKEN_PROBABILITY_NOT_CALIBRATED,
        "confidence_basis": BASIS_IMAGE_COLOUR_HEURISTIC,
        "uncertain": False,
        "green_pct": green_pct,
        "yellow_pct": yellow_pct,
        "brown_pct": brown_pct,
        "dark_pct": dark_pct,
        "evidence_score": int(evidence_score),
        "explanation": "LeafScan checks visible green cover, yellowing, brown lesion regions and dark patches from the uploaded image.",
        "recommendation": rec,
    }


def safe_analyze(file_storage: Any) -> dict[str, Any]:
    """Analysis wrapper that converts validation errors into honest states."""
    try:
        return analyze_leaf_image(file_storage)
    except InvalidImageError:
        result = empty_result()
        result.update({
            "available": False,
            "symptom": "Image not analysed",
            "explanation": "Use a clear JPG, PNG or WebP image under 5 MiB.",
        })
        return result


__all__ = ["analyze_leaf_image", "validate_upload", "empty_result", "safe_analyze"]
