"""Knowledge-request safety gate (Phase 7.2 §10/§11/§26/§47).

Deterministic rules, enforced in code and never delegated to a language model:

* **Manufacturing / synthesis / formulation** requests are refused outright.
  AGRIQ describes approved products and how the official label says to use
  them; it does not explain how to make a pesticide, how to synthesise an
  active ingredient or how to formulate one from raw chemicals.
* **Preparation recipes** are only ever restated from a reviewed source. When
  no verified preparation exists the answer is ``PREPARATION_DATA_UNAVAILABLE``
  — never a plausible-looking recipe.
* **Application details / dosage** are only stated from a reviewed source that
  documents them for the same product and crop. Otherwise the answer is
  ``APPLICATION_DATA_UNVERIFIED`` and points at the official label.
* **Chemical exposure** escalates immediately (reusing the Phase 2 exposure
  rules), with no model call at all.

Every outcome carries the canonical token from ``core.constants`` so the
interface, the API and tests branch on one vocabulary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.constants import (
    TOKEN_DATA_UNAVAILABLE,
    TOKEN_INSUFFICIENT_REAL_DATA,
)
from ..domain.safety.chemical_rules import check_chemical_request, looks_like_dosage_request
from ..i18n import DEFAULT_LANGUAGE, normalise_language, translate

#: Canonical refusal/state codes returned to clients.
REFUSAL_MANUFACTURING = "KNOWLEDGE_MANUFACTURING_REFUSED"
REFUSAL_PREPARATION = "PREPARATION_DATA_UNAVAILABLE"
REFUSAL_APPLICATION = "APPLICATION_DATA_UNVERIFIED"
REFUSAL_EMERGENCY = "KNOWLEDGE_CHEMICAL_EXPOSURE_ESCALATION"
STATE_OK = "OK"

_CHEMICAL_NOUN = (
    r"pesticide|insecticide|fungicide|herbicide|weedicide|rodenticide|acaricide|"
    r"chemical|poison|active ingredient|technical grade|औषध|कीटनाशक|ରାସାୟନିକ|କୀଟନାଶକ"
)

#: Asking AGRIQ how to *make* a pesticide (§10 — never answered).
#: Both orders are matched in every language ("manufacture a pesticide" and
#: "pesticide manufacturing"), because refusing only one phrasing would leave
#: an obvious gap in a safety rule.
_MANUFACTURE_VERBS = (r"manufactur\w*|synthes\w*|formulat\w*|production|produce|manufacturing"
                     r"|बनाने|बनाऊँ|बनाना|निर्माण|संश्लेषण|फॉर्मूला|तैयार"
                     r"|ତିଆରି|ନିର୍ମାଣ|ପ୍ରସ୍ତୁତ")

_MANUFACTURING_PATTERNS = (
    rf"\b({_MANUFACTURE_VERBS})\b.*\b({_CHEMICAL_NOUN})",
    rf"\b({_CHEMICAL_NOUN})\b.*\b({_MANUFACTURE_VERBS})\b",
    rf"\bhow\b.*\b(make|produce|prepare|mix|brew|create)\b.*\b(my own\s+)?({_CHEMICAL_NOUN})",
    rf"\b(make|produce|prepare|brew|create)\b.*\b({_CHEMICAL_NOUN})\b.*\bat home\b",
    rf"\bmy own\s+({_CHEMICAL_NOUN})",
    rf"\braw material(s)?\b.*\b({_CHEMICAL_NOUN})\b",
    rf"\bconcentrat(e|ed)\b.*\b({_CHEMICAL_NOUN})\b",
    r"(बनाने|बनाऊँ|बनाना|निर्माण|संश्लेषण|फॉर्मूला|तैयार).*(कीटनाशक|ज़हर|जहर|रासायनिक)",
    r"(कीटनाशक|ज़हर|जहर|रासायनिक).*(बनाने|बनाऊँ|बनाना|निर्माण|संश्लेषण|फॉर्मूला|तैयार)",
    r"(କୀଟନାଶକ|ରାସାୟନିକ).*(ତିଆରି|ନିର୍ମାଣ|ପ୍ରସ୍ତୁତ)",
    r"(ତିଆରି|ନିର୍ମାଣ|ପ୍ରସ୍ତୁତ).*(କୀଟନାଶକ|ରାସାୟନିକ)",
)

#: Asking for a preparation recipe (§9 — only from a reviewed source).
_RECIPE_PATTERNS = (
    r"\brecipe\b",
    r"\bhome ?made\b",
    rf"\b(natural|organic|desi)\b.*\b({_CHEMICAL_NOUN}|spray|solution)\b",
    r"\bmake\b.*\b(natural|organic|desi|neem|botanical)\b.*\b(spray|solution|extract|pesticide)\b",
    r"(नुस्खा|घरेलु|घरेलू|घरेलू).*(कीटनाशक|स्प्रे|घोल|कीट)",
    r"(कीट|कीटनाशक|स्प्रे|घोल).*(नुस्खा|घरेलु|घरेलू)",
    r"(ନୁସ୍ଖା|ଘରୋଇ|ମିଶ୍ରଣ).*(କୀଟନାଶକ|ସ୍ପ୍ରେ|ଘୋଳ|କୀଟ)",
)

#: Asking how it is applied / how much (§11).
_APPLICATION_PATTERNS = (
    r"\bhow (do|should) i (apply|spray|use|mix)\b",
    r"\bhow (is|to) (it )?(applied|sprayed|used)\b",
    r"\bspray (volume|rate|schedule|interval)\b",
    r"\bpre[- ]?harvest interval\b",
    r"(कैसे|कितना).*(छिड़काव|प्रयोग|मात्रा)",
    r"(କେମିତି|କେତେ).*(ସିଞ୍ଚଣ|ପ୍ରୟୋଗ|ମାତ୍ରା)",
)


def _match(text: str, patterns: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            hits.append(pattern)
    return hits


@dataclass
class KnowledgeSafetyResult:
    """Outcome of the knowledge-safety gate for one question."""

    blocked: bool = False
    status: str = STATE_OK
    refusal_code: Optional[str] = None
    message: str = ""
    message_key: Optional[str] = None
    requires_expert: bool = False
    escalate_emergency: bool = False
    matched_patterns: list[str] = field(default_factory=list)
    policy: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "status": self.status,
            "refusal_code": self.refusal_code,
            "message": self.message,
            "message_key": self.message_key,
            "requires_expert": self.requires_expert,
            "escalate_emergency": self.escalate_emergency,
            "policy": self.policy,
        }


def check_knowledge_request(
    question: str,
    *,
    language: Any = DEFAULT_LANGUAGE,
    field_area_known: bool = False,
    verified_preparation_available: bool = False,
    verified_application_available: bool = False,
    approved_dosage_evidence: bool = False,
) -> KnowledgeSafetyResult:
    """Evaluate one question against the knowledge safety policy.

    ``verified_*`` flags may only be set to True when a **review-verified**
    record documents that preparation/application for this exact product and
    crop. Everything else keeps the refusal: an unverified gap is reported as a
    state, never filled with generated text.
    """
    code = normalise_language(language)
    text = (question or "").strip()
    if not text:
        return KnowledgeSafetyResult(
            blocked=True,
            status=TOKEN_DATA_UNAVAILABLE,
            refusal_code="KNOWLEDGE_VALIDATION",
            message=translate("common.error_generic", code),
            message_key="common.error_generic",
        )

    # Emergency exposure first: it must never wait behind other rules.
    chemical = check_chemical_request(text, approved_dosage_evidence=True)
    if chemical.escalate_emergency:
        return KnowledgeSafetyResult(
            blocked=True,
            status="EMERGENCY_ESCALATION",
            refusal_code=REFUSAL_EMERGENCY,
            message=chemical.reason or "",
            requires_expert=True,
            escalate_emergency=True,
            policy="chemical_exposure",
        )

    manufacturing = _match(text, _MANUFACTURING_PATTERNS)
    if manufacturing:
        return KnowledgeSafetyResult(
            blocked=True,
            status=REFUSAL_MANUFACTURING,
            refusal_code=REFUSAL_MANUFACTURING,
            message=translate("pesticide.manufacturing_refusal", code),
            message_key="pesticide.manufacturing_refusal",
            requires_expert=False,
            matched_patterns=manufacturing,
            policy="no_manufacturing_instructions",
        )

    if looks_like_dosage_request(text) and not (verified_application_available and field_area_known):
        return KnowledgeSafetyResult(
            blocked=True,
            status=REFUSAL_APPLICATION,
            refusal_code=REFUSAL_APPLICATION,
            message=translate("knowledge_states.APPLICATION_DATA_UNVERIFIED", code),
            message_key="knowledge_states.APPLICATION_DATA_UNVERIFIED",
            requires_expert=True,
            policy="application_data_comes_from_labels",
        )

    if _match(text, _RECIPE_PATTERNS) and not verified_preparation_available:
        return KnowledgeSafetyResult(
            blocked=True,
            status=REFUSAL_PREPARATION,
            refusal_code=REFUSAL_PREPARATION,
            message=translate("knowledge_states.PREPARATION_DATA_UNAVAILABLE", code),
            message_key="knowledge_states.PREPARATION_DATA_UNAVAILABLE",
            requires_expert=True,
            policy="no_invented_recipes",
        )

    if _match(text, _APPLICATION_PATTERNS) and not verified_application_available:
        return KnowledgeSafetyResult(
            blocked=True,
            status=REFUSAL_APPLICATION,
            refusal_code=REFUSAL_APPLICATION,
            message=translate("knowledge_states.APPLICATION_DATA_UNVERIFIED", code),
            message_key="knowledge_states.APPLICATION_DATA_UNVERIFIED",
            requires_expert=False,
            policy="application_data_comes_from_labels",
        )

    if not approved_dosage_evidence and not verified_application_available:
        # Nothing blocked, but the turn must say which evidence is missing.
        return KnowledgeSafetyResult(
            status=TOKEN_INSUFFICIENT_REAL_DATA,
            message=translate("common.insufficient_real_data", code),
            message_key="common.insufficient_real_data",
            policy="state_missing_evidence",
        )

    return KnowledgeSafetyResult(status=STATE_OK)


__all__ = [
    "KnowledgeSafetyResult",
    "REFUSAL_APPLICATION",
    "REFUSAL_EMERGENCY",
    "REFUSAL_MANUFACTURING",
    "REFUSAL_PREPARATION",
    "STATE_OK",
    "check_knowledge_request",
]
