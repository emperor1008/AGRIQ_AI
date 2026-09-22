"""Common request-parsing helpers shared by blueprints."""
from __future__ import annotations

from typing import Any, Mapping

from ..core.constants import MAX_INPUT_LENGTH, MAX_QUESTION_LENGTH
from ..core.text import clean_text


def form_value(form: Mapping[str, Any], key: str, default: str = "", max_length: int = MAX_INPUT_LENGTH) -> str:
    """Read a cleaned, length-limited value from a form payload."""
    value = form.get(key, default)
    if value is None:
        return default
    return clean_text(str(value), max_length) or default


def question_value(payload: Mapping[str, Any]) -> str:
    """Extract a cleaned assistant question from a JSON payload."""
    raw = payload.get("question") or ""
    return clean_text(str(raw), MAX_QUESTION_LENGTH)


def context_value(payload: Mapping[str, Any]) -> dict[str, str]:
    """Extract a string-only context mapping from a JSON payload."""
    context = payload.get("context") or {}
    if not isinstance(context, dict):
        return {}
    return {str(k): str(v)[:MAX_INPUT_LENGTH] for k, v in context.items() if v is not None}


__all__ = ["form_value", "question_value", "context_value"]
