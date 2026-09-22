"""Advisory domain objects: evidence items, confidence scoring and the
structured recommendation payload (copilot-confidence-v1).

Every confidence number computed here traces to the documented formula in
docs/FARM_COPILOT.md (§Confidence) — no random or vibe-sourced numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

CONFIDENCE_VERSION = "copilot-confidence-v1"


@dataclass
class EvidenceItem:
    """One provenance-carrying fact used in a recommendation."""

    type: str                      # weather_forecast|weather_observation|farmer_record|knowledge|soil_test|market_record
    source: str
    observed_or_retrieved_at: Optional[str] = None
    detail: Optional[str] = None
    freshness: str = "unavailable"  # live|cached|stale|unavailable|n/a

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": self.type, "source": self.source}
        if self.observed_or_retrieved_at:
            payload["observed_or_retrieved_at"] = self.observed_or_retrieved_at
        if self.detail:
            payload["detail"] = self.detail
        payload["freshness"] = self.freshness
        return payload


@dataclass
class ConfidenceResult:
    """Explicit, documented confidence score."""

    level: str                     # high|medium|low
    score: float                   # 0.0-1.0
    basis: str
    calculation_version: str = CONFIDENCE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "score": round(self.score, 2),
            "basis": self.basis,
            "calculation_version": self.calculation_version,
        }


def compute_confidence(
    *,
    context_completeness: float,        # 0-1: verified farmer context fields present
    weather_fresh: bool,                # live/cached within TTL
    weather_present: bool,              # any weather evidence at all
    knowledge_top_score: float,         # 0-1 retrieval relevance of best chunk
    knowledge_present: bool,
    direct_observation: bool,           # farmer-recorded observation this cycle
    conflicting_evidence: bool,
    missing_critical_inputs: int,       # e.g. no soil test AND no confirmed stage
    weights: Optional[dict[str, float]] = None,
) -> ConfidenceResult:
    """Compute copilot confidence from documented factors.

    Formula (copilot-confidence-v1)::

        score = 0.30*context_completeness
              + 0.20*weather_factor          (1.0 fresh, 0.5 stale/cached, 0 absent)
              + 0.25*knowledge_factor        (top retrieval score; 0 if none)
              + 0.10*direct_observation      (1 if farmer observation exists)
        then penalties:
              -0.15 if conflicting evidence
              -0.08 per missing critical input (max 0.24)
    """
    w = weights or {}
    w_context = w.get("context", 0.30)
    w_weather = w.get("weather", 0.20)
    w_knowledge = w.get("knowledge", 0.25)
    w_obs = w.get("observation", 0.10)

    weather_factor = 0.0
    if weather_present:
        weather_factor = 1.0 if weather_fresh else 0.5

    knowledge_factor = max(0.0, min(1.0, knowledge_top_score)) if knowledge_present else 0.0

    score = (
        w_context * context_completeness
        + w_weather * weather_factor
        + w_knowledge * knowledge_factor
        + w_obs * (1.0 if direct_observation else 0.0)
    )
    if conflicting_evidence:
        score -= 0.15
    if missing_critical_inputs:
        score -= 0.08 * min(missing_critical_inputs, 3)

    score = max(0.0, min(1.0, score))

    if score >= 0.75:
        level = "high"
    elif score >= 0.50:
        level = "medium"
    else:
        level = "low"

    basis_parts: list[str] = []
    basis_parts.append(
        f"Farmer context is {'complete' if context_completeness >= 0.8 else 'partially complete' if context_completeness >= 0.5 else 'incomplete'}"
    )
    if weather_present:
        basis_parts.append("live weather is fresh" if weather_fresh else "weather data is cached or stale")
    else:
        basis_parts.append("no current weather data is available")
    if knowledge_present:
        basis_parts.append(f"best approved knowledge match scored {knowledge_factor:.2f}")
    else:
        basis_parts.append("no approved knowledge passage met the relevance threshold")
    if direct_observation:
        basis_parts.append("a farmer-recorded observation supports this cycle")
    else:
        basis_parts.append("no farmer observation supports this cycle yet")
    if conflicting_evidence:
        basis_parts.append("some evidence conflicts")
    if missing_critical_inputs:
        basis_parts.append(f"{missing_critical_inputs} critical input(s) missing")

    return ConfidenceResult(level=level, score=score, basis="; ".join(basis_parts))


@dataclass
class Recommendation:
    """A structured, evidence-backed recommendation (Phase 2 §11 contract)."""

    recommendation_type: str
    action: str
    reasons: list[str] = field(default_factory=list)
    evidence: list[EvidenceItem] = field(default_factory=list)
    confidence: Optional[ConfidenceResult] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    requires_expert_confirmation: bool = False
    missing_information: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_type": self.recommendation_type,
            "action": self.action,
            "reasons": list(self.reasons),
            "evidence": [e.to_dict() for e in self.evidence],
            "confidence": self.confidence.to_dict() if self.confidence else None,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "requires_expert_confirmation": self.requires_expert_confirmation,
            "missing_information": list(self.missing_information),
        }


def escalation_reasons(rec: Recommendation) -> list[str]:
    """Human-readable reasons this recommendation needs expert confirmation."""
    reasons: list[str] = []
    if rec.requires_expert_confirmation:
        reasons.append("Flagged by safety guardrails for expert confirmation.")
    if rec.confidence and rec.confidence.level == "low":
        reasons.append("Confidence is below the release threshold.")
    if rec.missing_information:
        reasons.append("Required information is missing: " + ", ".join(rec.missing_information))
    return reasons


__all__ = [
    "EvidenceItem", "ConfidenceResult", "Recommendation", "compute_confidence",
    "escalation_reasons", "CONFIDENCE_VERSION",
]
