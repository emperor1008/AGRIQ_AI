"""Chemical-safety rules for the copilot (Phase 2 §12).

These rules are deterministic and enforced in code — never delegated to the
LLM. They are intentionally conservative:

- No exact pesticide/fertiliser dosage without an approved knowledge passage
  that itself contains a verified dosage table AND a confirmed field area.
- No chemical mixing advice without label support.
- Spraying blocked under unsafe weather (wind, rain, heat) — weather evidence
  is required and must be fresh.
- No prohibited/chemistry-specific product names are listed here; the point
  is to block *exact prescriptions* unless approved evidence exists.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# Dosage-request patterns (EN + HI + OR transliterations). These detect the
# farmer asking "how much should I spray/spray X ml/g per acre" etc.
_DOSAGE_PATTERNS = (
    r"\b\d+\s*(ml|gm?|g|kg|litre|liter|l)\b",
    r"\b(per\s*(acre|hectare|bigha|guntha|decare))\b",
    r"\b(dose|dosage|quantity|how much|how many)\b.*\b(spray|pesticide|insecticide|fungicide|urea|fertilizer|fertiliser|dap|potash)\b",
    r"\b(spray|pesticide|insecticide|fungicide|urea|fertilizer|fertiliser|dap|potash)\b.*\b(dose|dosage|quantity|how much|how many)\b",
    r"कितना\s*(छिड़काव|डोज|मात्रा)",
    r"कितने\s*(प्रति|एकड़|हेक्टेयर)",
    r"କେତେ\s*(ମାତ୍ରା|ଡୋଜ|ସିଞ୍ଚଣ)",
)

_MIXING_PATTERNS = (
    r"\bmix(ed|ing)?\b.*\b(pesticide|chemical|insecticide|fungicide|herbicide|spray)\b",
    r"\b(cocktail|tank mix)\b",
    r"मिलाकर\s*(छिड़काव|स्प्रे)",
    r"ମିଶାଇ\s*(ସିଞ୍ଚଣ|ସ୍ପ୍ରେ)",
)

_EXPOSURE_PATTERNS = (
    r"\b(poison(ed|ing)?|swallow(ed)?|inhale|drank|drinking|accident|emergency|hospital|vomit)\b",
    r"ज़हर|विष|जहर",
    r"ବିଷ|ଝାଡ଼ିପକାଇଲା|ଦୁର୍ଘଟଣା",
)


@dataclass
class ChemicalSafetyResult:
    """Outcome of running the chemical safety rules."""

    blocked: bool = False
    reason: Optional[str] = None
    requires_expert: bool = False
    escalate_emergency: bool = False
    matched_patterns: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "reason": self.reason,
            "requires_expert": self.requires_expert,
            "escalate_emergency": self.escalate_emergency,
        }


def _any_match(text: str, patterns: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(pattern)
    return hits


def check_chemical_request(
    question: str,
    *,
    approved_dosage_evidence: bool = False,
    field_area_known: bool = False,
    weather_safe: Optional[bool] = None,
    weather_fresh: bool = False,
) -> ChemicalSafetyResult:
    """Evaluate a farmer question against the chemical safety rules.

    Parameters
    ----------
    approved_dosage_evidence:
        True only when an *approved* knowledge chunk containing a verified
        dosage recommendation was actually retrieved for this question.
    field_area_known:
        True only when the selected field has a verified area value.
    weather_safe:
        True/False when fresh weather exists; None when unavailable. Spraying
        advice requires weather to be both fresh and safe.
    """
    result = ChemicalSafetyResult()

    # Emergency exposure always escalates immediately — no LLM content needed.
    exposure_hits = _any_match(question, _EXPOSURE_PATTERNS)
    if exposure_hits:
        result.escalate_emergency = True
        result.requires_expert = True
        result.blocked = True
        result.reason = (
            "This sounds like a possible chemical exposure emergency. "
            "Please contact your nearest health centre or call emergency services immediately."
        )
        result.matched_patterns = exposure_hits
        return result

    mixing_hits = _any_match(question, _MIXING_PATTERNS)
    if mixing_hits:
        result.blocked = True
        result.requires_expert = True
        result.reason = (
            "Chemical mixing advice requires label-verified guidance. "
            "Please consult your local KVK or agriculture officer."
        )
        result.matched_patterns = mixing_hits
        return result

    dosage_hits = _any_match(question, _DOSAGE_PATTERNS)
    if dosage_hits:
        # Exact dosage needs BOTH approved evidence and a known field area.
        if approved_dosage_evidence and field_area_known:
            result.requires_expert = False
            result.reason = None
            return result
        result.blocked = True
        result.requires_expert = True
        if not approved_dosage_evidence:
            result.reason = (
                "No approved source supports a specific dosage recommendation "
                "for your crop and region. Please consult your local KVK or "
                "agriculture officer for exact quantities."
            )
        elif not field_area_known:
            result.reason = (
                "A verified field area is required before any quantity can be "
                "discussed. Please record your field area first."
            )
        result.matched_patterns = dosage_hits
        return result

    # Unsprayed-weather gate: any spray advice needs fresh, safe weather.
    if weather_safe is False or (weather_safe is True and not weather_fresh):
        result.blocked = True
        result.reason = (
            "Spraying is not advised under the current weather conditions. "
            "Please wait for calm, dry conditions."
        )
        return result
    if weather_safe is None:
        # Cannot confirm safe spraying conditions — do not give spray advice.
        result.requires_expert = True
        result.reason = (
            "Current weather data is unavailable, so spraying conditions "
            "cannot be verified. Live weather is currently unavailable."
        )
        return result

    return result


__all__ = ["ChemicalSafetyResult", "check_chemical_request"]
