"""Phase 4 unit tests: ml.inference quality gate, abstention, registry gating
and the fail-closed predictor.

All fixtures here are SYNTHETIC test images generated in-memory (Pillow) and
stay inside the test module — they never touch production storage and are
never presented as real farmer data.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from PIL import Image

API_DIR = Path(__file__).resolve().parents[1]
ROOT = API_DIR.parents[2]  # AGRIQ_AI-main repo root (contains ml/)
for p in (str(API_DIR), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from ml.inference.abstention import decide  # noqa: E402
from ml.inference.quality import check_image  # noqa: E402
from ml.inference.registry import ModelRegistry  # noqa: E402


# -- synthetic fixtures (clearly test-only) -----------------------------------

def _leaf_like_png(size: tuple[int, int] = (800, 800), brightness: int = 110) -> bytes:
    """A green-dominant, textured image — passes the leaf-signal and blur
    checks (per-pixel diagonal gradient gives a high edge score)."""
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            g = min(255, brightness + ((x * 7 + y * 13) % 60))
            px[x, y] = (max(0, g - 40), g, max(0, g - 30))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _dark_png() -> bytes:
    img = Image.new("RGB", (800, 800))
    px = img.load()
    for y in range(800):
        for x in range(800):
            g = (x * 7 + y * 13) % 20
            px[x, y] = (g, g + 5, g)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _flat_png() -> bytes:
    """Low-variance image — fails the blur (detail) check."""
    img = Image.new("RGB", (800, 800), (70, 120, 60))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _non_leaf_png() -> bytes:
    img = Image.new("RGB", (800, 800), (200, 200, 200))  # grey document-like
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


GOOD_QUALITY = check_image(Image.open(io.BytesIO(_leaf_like_png())), file_bytes=1000)


def _predictions(top: float, second: float | None = None) -> list[dict]:
    preds = [{"condition": "rice_blast", "probability": top}]
    if second is not None:
        preds.append({"condition": "rice_brown_spot", "probability": second})
    return preds


# -- quality gate -------------------------------------------------------------

class TestQualityGate:
    def test_leaf_like_image_accepted(self):
        result = check_image(Image.open(io.BytesIO(_leaf_like_png())), file_bytes=1000)
        assert result.accepted, result.issues

    def test_dark_image_rejected_with_guidance(self):
        result = check_image(Image.open(io.BytesIO(_dark_png())), file_bytes=1000)
        assert not result.accepted
        assert "too_dark" in result.issues
        assert result.guidance, "farmer must receive actionable retake guidance"

    def test_flat_image_rejected_as_blurry(self):
        result = check_image(Image.open(io.BytesIO(_flat_png())), file_bytes=1000)
        assert "blurry" in result.issues

    def test_oversize_file_rejected(self):
        result = check_image(Image.open(io.BytesIO(_leaf_like_png())), file_bytes=10 * 1024 * 1024)
        assert not result.accepted
        assert "file_too_large" in result.issues

    def test_non_leaf_image_rejected(self):
        result = check_image(Image.open(io.BytesIO(_non_leaf_png())), file_bytes=1000)
        assert "low_leaf_signal" in result.issues

    def test_tiny_image_rejected(self):
        result = check_image(Image.open(io.BytesIO(_leaf_like_png((120, 120)))), file_bytes=1000)
        assert "too_small" in result.issues


# -- abstention ---------------------------------------------------------------

class TestAbstention:
    THRESHOLDS = {"min_probability": 0.55, "margin_ratio": 0.15}

    def test_low_confidence_abstains(self):
        d = decide(quality=GOOD_QUALITY, crop_supported=True, expected_crop="rice",
                   detected_crop="rice", predictions=_predictions(0.40),
                   thresholds=self.THRESHOLDS, model_available=True)
        assert d.abstained and d.reason == "low_confidence"

    def test_close_top_predictions_abstain(self):
        d = decide(quality=GOOD_QUALITY, crop_supported=True, expected_crop="rice",
                   detected_crop="rice", predictions=_predictions(0.80, 0.78),
                   thresholds=self.THRESHOLDS, model_available=True)
        assert d.abstained and d.reason == "top_predictions_too_close"

    def test_crop_mismatch_abstains(self):
        d = decide(quality=GOOD_QUALITY, crop_supported=True, expected_crop="rice",
                   detected_crop="tomato", predictions=_predictions(0.9),
                   thresholds={}, model_available=True)
        assert d.abstained and d.reason == "crop_mismatch"

    def test_unsupported_crop_abstains(self):
        d = decide(quality=GOOD_QUALITY, crop_supported=False, expected_crop="mango",
                   detected_crop=None, predictions=_predictions(0.9),
                   thresholds={}, model_available=True)
        assert d.abstained and d.reason == "crop_not_supported"

    def test_bad_quality_abstains(self):
        bad = check_image(Image.open(io.BytesIO(_dark_png())), file_bytes=1000)
        d = decide(quality=bad, crop_supported=True, expected_crop="rice",
                   detected_crop="rice", predictions=_predictions(0.9),
                   thresholds={}, model_available=True)
        assert d.abstained and d.reason == "image_quality_insufficient"

    def test_missing_model_abstains(self):
        d = decide(quality=GOOD_QUALITY, crop_supported=True, expected_crop="rice",
                   detected_crop="rice", predictions=_predictions(0.9),
                   thresholds={}, model_available=False)
        assert d.abstained and d.reason == "model_unavailable"

    def test_strong_single_prediction_passes(self):
        d = decide(quality=GOOD_QUALITY, crop_supported=True, expected_crop="rice",
                   detected_crop="rice", predictions=_predictions(0.9),
                   thresholds=self.THRESHOLDS, model_available=True)
        assert not d.abstained


# -- registry gating ----------------------------------------------------------

class TestModelRegistry:
    def test_empty_registry_has_no_approved_models(self):
        registry = ModelRegistry()
        assert registry.entries == []
        assert registry.approved_for_crop("rice") is None
        assert registry.approved_for_crop("tomato") is None

    def test_approved_entry_requires_existing_weights(self, tmp_path):
        import yaml

        reg = tmp_path / "registry.yaml"
        reg.write_text(yaml.safe_dump({
            "models": [{
                "model_id": "test-rice", "model_name": "agriq-rice-screening",
                "version": "1.0.0", "supported_crop": "rice",
                "supported_classes": ["rice_blast", "rice_healthy"],
                "model_checksum": "0" * 64, "framework": "pytorch",
                "input_size": [224, 224], "preprocessing_version": "v1",
                "dataset_manifest_versions": ["ds-v1"], "split_manifest": "splits-v1",
                "calibration_version": "cal-v1",
                "abstention_thresholds": {"min_probability": 0.55},
                "evaluation_report": "reports/test.md",
                "external_field_validation_status": "in_progress",
                "licence": "CC-BY-4.0", "approved_for_production": True,
                "approved_at": "2026-09-23T00:00:00Z", "approver": "test",
                "weights_path": "missing.pt",
            }]
        }))
        registry = ModelRegistry(registry_path=reg, models_dir=tmp_path)
        # Weights missing → fail closed even though approved_for_production.
        assert registry.approved_for_crop("rice") is None

    def test_checksum_mismatch_fails_closed(self, tmp_path):
        import yaml

        weights = tmp_path / "model.pt"
        weights.write_bytes(b"weights")
        reg = tmp_path / "registry.yaml"
        reg.write_text(yaml.safe_dump({
            "models": [{
                "model_id": "test-rice", "model_name": "m", "version": "1",
                "supported_crop": "rice", "supported_classes": ["rice_healthy"],
                "model_checksum": "f" * 64, "framework": "pytorch",
                "input_size": [224, 224], "preprocessing_version": "v1",
                "dataset_manifest_versions": [], "split_manifest": "s",
                "calibration_version": "c", "abstention_thresholds": {},
                "evaluation_report": "r", "external_field_validation_status": "in_progress",
                "licence": "MIT", "approved_for_production": True,
                "weights_path": "model.pt",
            }]
        }))
        registry = ModelRegistry(registry_path=reg, models_dir=tmp_path)
        assert registry.approved_for_crop("rice") is None


# -- predictor fail-closed ----------------------------------------------------

class TestPredictorFailClosed:
    def test_unavailable_when_no_approved_model(self):
        from ml.inference.predictor import CropImagePredictor

        result = CropImagePredictor().analyse(_leaf_like_png(), expected_crop="rice")
        assert result.status == "unavailable"
        assert result.message == "Image analysis is not currently available."
        # No fabricated predictions anywhere in the payload.
        assert not result.analysis.get("predictions")

    def test_unsupported_crop_reports_unavailable(self):
        from ml.inference.predictor import CropImagePredictor

        result = CropImagePredictor().analyse(_leaf_like_png(), expected_crop="mango")
        assert result.status == "unavailable"


# -- schema validation --------------------------------------------------------

class TestImageSchemas:
    def test_unsupported_crop_rejected(self):
        from agriq.core.exceptions import ValidationError
        from agriq.schemas.image_analysis import validate_analyse_request

        with pytest.raises(ValidationError):
            validate_analyse_request(expected_crop="mango")
        with pytest.raises(ValidationError):
            validate_analyse_request(expected_crop=None)

    def test_supported_crops_normalised(self):
        from agriq.schemas.image_analysis import validate_analyse_request

        assert validate_analyse_request(expected_crop="Rice") == "rice"
        assert validate_analyse_request(expected_crop=" TOMATO ") == "tomato"

    def test_feedback_validation(self):
        from agriq.core.exceptions import ValidationError
        from agriq.schemas.image_analysis import validate_feedback

        assert validate_feedback(" It helped ") == "It helped"
        with pytest.raises(ValidationError):
            validate_feedback("   ")
        with pytest.raises(ValidationError):
            validate_feedback("x" * 2001)
