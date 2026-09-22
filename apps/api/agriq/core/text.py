"""Text normalisation and validation helpers (03_SECURITY_AND_ACCESS.md)."""
from __future__ import annotations

from .constants import MAX_INPUT_LENGTH


def clean_text(value: str | None, max_length: int = MAX_INPUT_LENGTH) -> str:
    """Strip and length-limit any user-provided text field."""
    if value is None:
        return ""
    return str(value).strip()[:max_length]


def has_any(text: str, words: list[str] | tuple[str, ...]) -> bool:
    """Case-insensitive keyword match helper used by the answer engines."""
    haystack = " " + (text or "").lower() + " "
    return any(word.lower() in haystack for word in words)


def format_list(title: str, items: list[str]) -> str:
    """Render a bulleted plain-text list under a title."""
    return title + "\n" + "\n".join(f"• {item}" for item in items)


def clamp_str(value: str | None, fallback: str) -> str:
    """Return a non-empty stripped string or the fallback."""
    value = clean_text(value)
    return value or fallback


__all__ = ["clean_text", "has_any", "format_list", "clamp_str"]
