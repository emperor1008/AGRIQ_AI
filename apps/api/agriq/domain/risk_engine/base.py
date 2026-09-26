"""Analyzer contract shared by every risk analyzer (Phase 5 §7).

``Assessment`` is the normalized result shape. Probability (likelihood the
condition exists/occurs) and confidence (trust in the assessment quality) are
independent fields throughout — backend, DB, API, UI (§8).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

RISK_TYPES = (
    "disease_conducive_weather",
    "heavy_rain_flooding",
    "heat_stress",
    "water_stress",
    "market_volatility",
)

SUPPORTED_CROPS = ("rice", "tomato")

# Valid statuses for a generated assessment (§9).
VALID_STATUSES = (
    "inactive",
    "monitor",
    "elevated",
    "high",
    "critical",
    "data_unavailable",
    "insufficient_data",
)

# ---------------------------------------------------------------------------
# Assessment-method provenance (§7, §17, §20)
# ---------------------------------------------------------------------------
#: Which kind of machinery produced the numbers. The five analyzers shipped
#: today are deterministic rules, so every live assessment is ``rule_based``.
#: ``ml`` / ``hybrid`` are representable so a validated, registered model can
#: replace an analyzer later WITHOUT any caller having to guess provenance.
ASSESSMENT_METHODS = ("rule_based", "ml", "hybrid")

#: What the ``probability`` number actually is. A rule score is a documented
#: deterministic screening estimate; it is NOT a calibrated event
#: probability and must never be described as one (§5).
PROBABILITY_KINDS = ("rule_score", "uncalibrated_ml_probability", "calibrated_probability")

#: Calibration status of the produced number (§17). "not_validated" is the
#: truthful value until a real evaluation supports the interpretation.
CALIBRATION_STATUSES = ("not_validated", "validated", "not_applicable")

#: Human-readable explanation of what a probability number means, shown next
#: to the number itself so it can never be read as a calibrated guarantee.
PROBABILITY_INTERPRETATION = {
    "rule_score": (
        "rule-derived screening estimate from documented thresholds — not a "
        "calibrated probability of the event occurring"
    ),
    "uncalibrated_ml_probability": (
        "model output that has not passed calibration review — do not read it "
        "as a calibrated event probability"
    ),
    "calibrated_probability": (
        "calibrated probability; interpretation is supported only for the "
        "validated evaluation scope recorded with the model"
    ),
}


@dataclass
class Evidence:
    """One verified input item backing an assessment."""

    type: str                      # weather_observation | weather_forecast | market_record | farmer_record | image_screening
    source: str                    # "Open-Meteo", "AGMARKNET", "Crop cycle 41", ...
    observed_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    freshness: str = "unavailable"  # fresh | aging | stale | expired | unavailable
    detail: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "source": self.source,
            "observed_at": self.observed_at,
            "retrieved_at": self.retrieved_at,
            "freshness": self.freshness,
            "detail": self.detail,
        }


@dataclass
class Assessment:
    """Normalized analyzer output (§7 contract)."""

    risk_type: str
    status: str
    probability: Optional[float] = None
    confidence: Optional[float] = None
    confidence_basis: Optional[str] = None
    severity: Optional[str] = None
    urgency: Optional[str] = None
    warning_lead_time_hours: Optional[int] = None
    threat: Optional[str] = None
    reasons: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    data_quality: dict[str, Any] = field(default_factory=dict)
    requires_expert_confirmation: bool = False
    unavailable_reason: Optional[str] = None
    #: Producing machinery: rule_based | ml | hybrid (§7).
    assessment_method: str = "rule_based"
    #: What ``probability`` is: rule_score | uncalibrated_ml_probability |
    #: calibrated_probability. None when no probability was produced (§5).
    probability_kind: Optional[str] = "rule_score"
    #: Calibration state of ``probability`` (§17).
    calibration_status: str = "not_validated"

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_type": self.risk_type,
            "status": self.status,
            "probability": self.probability,
            "severity": self.severity,
            "urgency": self.urgency,
            "warning_lead_time_hours": self.warning_lead_time_hours,
            "confidence": self.confidence,
            "confidence_basis": self.confidence_basis,
            "threat": self.threat,
            "reasons": list(self.reasons),
            "actions": list(self.actions),
            "evidence": [e.to_dict() if hasattr(e, "to_dict") else dict(e) for e in self.evidence],
            "data_quality": dict(self.data_quality),
            "requires_expert_confirmation": self.requires_expert_confirmation,
            "unavailable_reason": self.unavailable_reason,
            "assessment_method": self.assessment_method,
            "probability_kind": self.probability_kind,
            "calibration_status": self.calibration_status,
            "probability_interpretation": (
                PROBABILITY_INTERPRETATION.get(self.probability_kind) if self.probability_kind else None
            ),
        }


def unavailable(risk_type: str, reason: str, evidence: list[Evidence] | None = None) -> Assessment:
    """Honest DATA_UNAVAILABLE result — never a guessed value (§1, §47)."""
    return Assessment(
        risk_type=risk_type,
        status="data_unavailable",
        unavailable_reason=reason,
        evidence=evidence or [],
        data_quality={"inputs_available": False, "reason": reason},
        # No probability was produced at all, so there is nothing to calibrate.
        probability_kind=None,
        calibration_status="not_applicable",
    )


def insufficient(risk_type: str, reason: str, evidence: list[Evidence] | None = None) -> Assessment:
    """INSUFFICIENT_DATA — inputs exist but do not support an assessment."""
    return Assessment(
        risk_type=risk_type,
        status="insufficient_data",
        unavailable_reason=reason,
        evidence=evidence or [],
        data_quality={"inputs_available": True, "sufficient": False, "reason": reason},
        probability_kind=None,
        calibration_status="not_applicable",
    )


def confidence_from(factors: Mapping[str, Optional[float]], basis: str) -> tuple[float, str]:
    """Documented confidence formula (§11): weighted product of quality factors.

    Each factor in [0, 1]; None counts as 0. The formula version is pinned so
    historical assessments stay interpretable.
    """
    weights = {"input_freshness": 0.4, "context_completeness": 0.3, "evidence_directness": 0.3}
    score = 1.0
    used: list[str] = []
    for name, weight in weights.items():
        value = factors.get(name)
        value = 0.0 if value is None else max(0.0, min(1.0, float(value)))
        # Weighted geometric-style combination: missing factors pull hard down.
        score *= value ** weight
        used.append(f"{name}={value:.2f}")
    return round(score, 2), f"copilot-confidence-v1 ({', '.join(used)}; {basis})"


__all__ = [
    "RISK_TYPES",
    "SUPPORTED_CROPS",
    "VALID_STATUSES",
    "ASSESSMENT_METHODS",
    "PROBABILITY_KINDS",
    "CALIBRATION_STATUSES",
    "PROBABILITY_INTERPRETATION",
    "Evidence",
    "Assessment",
    "unavailable",
    "insufficient",
    "confidence_from",
]
