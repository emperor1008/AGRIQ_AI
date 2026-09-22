"""Language service (Phase 3).

The closed set of languages AGRIQ voice supports. Anything else is refused
with a clear message — no silent language switching, no unsupported-dialect
claims. Automatic language detection is intentionally NOT offered as an
input mode in Phase 3; the ASR result's ``language_detected`` is recorded
for transparency only.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceLanguage:
    code: str            # internal code (or|hi|en-IN)
    display: str         # farmer-facing label
    speech_code: str     # provider-side code


SUPPORTED: dict[str, VoiceLanguage] = {
    "or": VoiceLanguage("or", "ଓଡ଼ିଆ (Odia)", "or"),
    "hi": VoiceLanguage("hi", "हिन्दी (Hindi)", "hi"),
    "en-IN": VoiceLanguage("en-IN", "English (India)", "en-IN"),
}

DEFAULT_LANGUAGE = "en-IN"


def is_supported(code: str | None) -> bool:
    return (code or "") in SUPPORTED


def normalise(code: str | None) -> str:
    """Map near-miss inputs ('en', 'EN', 'en_IN') onto supported codes."""
    cleaned = (code or "").strip()
    aliases = {"en": "en-IN", "en_in": "en-IN", "en-in": "en-IN"}
    candidate = aliases.get(cleaned.lower(), cleaned)
    return candidate if candidate in SUPPORTED else DEFAULT_LANGUAGE


def language_or_error(code: str | None) -> VoiceLanguage:
    candidate = normalise(code)
    if not is_supported(candidate):
        # normalise() always returns a supported code, so this is defensive.
        raise ValueError(f"Language {code} is not supported.")
    return SUPPORTED[candidate]


__all__ = ["VoiceLanguage", "SUPPORTED", "DEFAULT_LANGUAGE",
           "is_supported", "normalise", "language_or_error"]
