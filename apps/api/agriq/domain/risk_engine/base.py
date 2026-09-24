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
        }


def unavailable(risk_type: str, reason: str, evidence: list[Evidence] | None = None) -> Assessment:
    """Honest DATA_UNAVAILABLE result — never a guessed value (§1, §47)."""
    return Assessment(
        risk_type=risk_type,
        status="data_unavailable",
        unavailable_reason=reason,
        evidence=evidence or [],
        data_quality={"inputs_available": False, "reason": reason},
    )


def insufficient(risk_type: str, reason: str, evidence: list[Evidence] | None = None) -> Assessment:
    """INSUFFICIENT_DATA — inputs exist but do not support an assessment."""
    return Assessment(
        risk_type=risk_type,
        status="insufficient_data",
        unavailable_reason=reason,
        evidence=evidence or [],
        data_quality={"inputs_available": True, "sufficient": False, "reason": reason},
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
    "Evidence",
    "Assessment",
    "unavailable",
    "insufficient",
    "confidence_from",
]
