"""Phase 4 image-analysis request validation (server-side, route-independent)."""
from __future__ import annotations

from ..core.exceptions import ValidationError

SUPPORTED_CROPS = {"rice", "tomato"}


def validate_analyse_request(*, expected_crop: str | None) -> str:
    """Validate the expected-crop declaration; returns the normalised crop.

    The crop comes from the farmer's own selection (the persisted crop cycle
    is preferred). An unknown/unsupported crop is a clean 400 — the model
    never silently analyses it.
    """
    if not expected_crop or not str(expected_crop).strip():
        raise ValidationError("Select your crop before uploading an image.")
    crop = str(expected_crop).strip().lower()
    if crop not in SUPPORTED_CROPS:
        raise ValidationError("This crop is not supported by the current validated model.")
    return crop


def validate_feedback(farmer_feedback: str | None) -> str:
    if farmer_feedback is None or not str(farmer_feedback).strip():
        raise ValidationError("Please describe what you observed before submitting feedback.")
    text = str(farmer_feedback).strip()
    if len(text) > 2000:
        raise ValidationError("Feedback is too long (maximum 2000 characters).")
    return text


__all__ = ["SUPPORTED_CROPS", "validate_analyse_request", "validate_feedback"]
