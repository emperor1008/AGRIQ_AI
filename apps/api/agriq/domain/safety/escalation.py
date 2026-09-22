"""Escalation policy: when the copilot must hand over to a human expert.

Escalation is a safety feature, not a failure state. The conditions below are
evaluated by the orchestrator *before* any LLM call; escalation short-circuits
the model answer with a clear farmer-facing handover message.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..advisory.recommendation import ConfidenceResult


@dataclass
class EscalationDecision:
    """Whether to escalate and why (farmer-facing, non-technical)."""

    escalate: bool = False
    reasons: list[str] = field(default_factory=list)
    urgency: str = "routine"          # routine|soon|immediate
    handover_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "escalate": self.escalate,
            "reasons": list(self.reasons),
            "urgency": self.urgency,
            "handover_message": self.handover_message,
        }


_IMMEDIATE_HANDOVER = (
    "Please contact your nearest KVK, agriculture officer or doctor immediately."
)
_SOON_HANDOVER = (
    "Please plan a visit or call to your local KVK / agriculture officer "
    "for a field-level check."
)


def evaluate_escalation(
    *,
    confidence: Optional[ConfidenceResult] = None,
    severe_symptoms: bool = False,
    symptoms_spreading: bool = False,
    condition_unsupported: bool = False,
    conflicting_evidence: bool = False,
    exact_chemical_requested: bool = False,
    emergency_exposure: bool = False,
    crop_loss_substantial: bool = False,
) -> EscalationDecision:
    """Deterministic escalation policy (Phase 2 §12)."""
    decision = EscalationDecision()

    if emergency_exposure:
        decision.escalate = True
        decision.urgency = "immediate"
        decision.reasons.append("Possible unsafe chemical exposure mentioned.")
        decision.handover_message = _IMMEDIATE_HANDOVER
        return decision

    if severe_symptoms:
        decision.escalate = True
        decision.urgency = "soon"
        decision.reasons.append("Reported symptoms are severe.")
    if symptoms_spreading:
        decision.escalate = True
        decision.urgency = "soon"
        decision.reasons.append("Symptoms are reported to be spreading rapidly.")
    if crop_loss_substantial:
        decision.escalate = True
        decision.urgency = "soon"
        decision.reasons.append("Reported crop loss appears substantial.")
    if condition_unsupported:
        decision.escalate = True
        decision.reasons.append("The crop condition cannot be supported by verified evidence.")
    if conflicting_evidence:
        decision.escalate = True
        decision.reasons.append("Available evidence conflicts and needs expert review.")
    if exact_chemical_requested:
        decision.escalate = True
        decision.reasons.append("Exact chemical selection or dosage was requested.")

    if confidence is not None and confidence.level == "low":
        decision.escalate = True
        decision.reasons.append("Confidence is below the release threshold.")

    if decision.escalate:
        decision.urgency = "immediate" if decision.urgency == "immediate" else (
            "soon" if "soon" == decision.urgency or decision.reasons else "routine"
        )
        decision.handover_message = (
            _IMMEDIATE_HANDOVER if decision.urgency == "immediate" else _SOON_HANDOVER
        )
    return decision


__all__ = ["EscalationDecision", "evaluate_escalation"]
