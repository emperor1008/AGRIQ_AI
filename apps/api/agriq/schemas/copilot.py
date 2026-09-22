"""Request parsers for the versioned copilot API (Phase 2 §2)."""
from __future__ import annotations

from typing import Any, Mapping

from ..core.exceptions import ValidationError
from ..core.text import clean_text

_MAX_QUESTION = 2000
_LANGUAGES = {"en", "hi", "or"}


def parse_copilot_message(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate POST /api/v1/copilot/messages body.

    user_id is NEVER accepted from the payload — it always comes from the
    authenticated session at the route layer.
    """
    question = clean_text(str(payload.get("question") or ""), _MAX_QUESTION)
    if not question:
        raise ValidationError("Type your question for the copilot.")

    language = str(payload.get("language") or "en").strip().lower()
    if language not in _LANGUAGES:
        raise ValidationError("Language must be one of: en, hi, or.")

    data: dict[str, Any] = {
        "question": question,
        "language": language,
        "conversation_id": payload.get("conversation_id") or None,
        "field_id": payload.get("field_id"),
        "crop_cycle_id": payload.get("crop_cycle_id"),
    }
    # Field/cycle ids must be positive integers when provided.
    for key in ("field_id", "crop_cycle_id"):
        value = data[key]
        if value in (None, ""):
            data[key] = None
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise ValidationError(f"{key} must be a valid id.")
        if number <= 0:
            raise ValidationError(f"{key} must be a valid id.")
        data[key] = number
    return data


def parse_feedback_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate POST /api/v1/recommendations/{id}/feedback body."""
    status = str(payload.get("status") or "").strip().lower()
    helpfulness = payload.get("helpfulness")
    if helpfulness not in (None, ""):
        try:
            helpfulness = int(helpfulness)
        except (TypeError, ValueError):
            raise ValidationError("Helpfulness must be a number from 1 to 5.")
        if not 1 <= helpfulness <= 5:
            raise ValidationError("Helpfulness must be a number from 1 to 5.")
    else:
        helpfulness = None
    return {
        "status": status,
        "helpfulness": helpfulness,
        "farmer_note": clean_text(str(payload.get("farmer_note") or ""), 1000) or None,
        "outcome": clean_text(str(payload.get("outcome") or ""), 1000) or None,
    }


__all__ = ["parse_copilot_message", "parse_feedback_payload"]
