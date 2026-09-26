"""LeafScan service unit tests: validation + transparent screening (ARC-07)."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from agriq.core.exceptions import InvalidImageError
from agriq.services import leaf_analysis


def _png_bytes(color=(60, 140, 60), size=(300, 300)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


class _Upload:
    def __init__(self, filename: str, data: bytes, mimetype: str = "image/png"):
        self.filename = filename
        self.data = data
        self.mimetype = mimetype

    def read(self):
        return self.data


def test_missing_file_raises():
    with pytest.raises(InvalidImageError):
        leaf_analysis.analyze_leaf_image(None)


def test_empty_filename_raises():
    with pytest.raises(InvalidImageError):
        leaf_analysis.analyze_leaf_image(_Upload("", _png_bytes()))


def test_disallowed_extension_raises():
    with pytest.raises(InvalidImageError):
        leaf_analysis.analyze_leaf_image(_Upload("evil.gif", _png_bytes()))


def test_oversized_image_raises():
    with pytest.raises(InvalidImageError):
        leaf_analysis.analyze_leaf_image(_Upload("big.png", b"x" * (6 * 1024 * 1024)))


def test_corrupt_image_raises():
    with pytest.raises(InvalidImageError):
        leaf_analysis.analyze_leaf_image(_Upload("broken.png", b"not-an-image"))


def test_valid_leaf_image_returns_screening():
    result = leaf_analysis.analyze_leaf_image(_Upload("leaf.png", _png_bytes()))
    assert result["available"] is True
    assert result["preview"] is not None
    assert 0 <= result["confidence"] <= 100
    # screening language, never diagnosis claims
    assert "diagnos" not in result["symptom"].lower()


def test_safe_analyze_degrades_to_honest_state():
    result = leaf_analysis.safe_analyze(_Upload("bad.png", b"junk"))
    assert result["available"] is False
    assert "JPG, PNG or WebP" in result["explanation"]
    # Phase 7 F-04: an unanalysed image is an explicit unavailable state.
    assert result["confidence_status"] == "DATA_UNAVAILABLE"


def test_screening_confidence_is_labelled_uncalibrated():
    """Phase 7 F-04: the number is a colour-heuristic band, not a model score."""
    result = leaf_analysis.analyze_leaf_image(_Upload("leaf.png", _png_bytes()))

    assert result["confidence_status"] == "PROBABILITY_NOT_CALIBRATED"
    assert result["confidence_basis"]
    assert "colour-pattern" in result["confidence_basis"].lower()
    assert result["uncertain"] is False


def test_unclear_image_is_marked_uncertain():
    """Phase 7 §15: too little leaf area must not be forced into a symptom band."""
    grey = _png_bytes(color=(128, 128, 128))
    result = leaf_analysis.analyze_leaf_image(_Upload("grey.png", grey))

    assert result["symptom"] == "Unclear leaf area"
    assert result["confidence_status"] == "IMAGE_ANALYSIS_UNCERTAIN"
    assert result["uncertain"] is True
