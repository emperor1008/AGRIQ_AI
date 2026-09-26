"""Explainable risk scoring components (ARC-07).

Pure rule logic over the crop knowledge record, verified weather and
optional LeafScan evidence. Every score shown to the user is traceable to
one of these named components.

HONEST STATUS (Phase 7 §2/§3/§13) — read before using any value here:

- These are **rule-based heuristics**. None of them is a trained model, a
  validated index or a field measurement. Their weights below are hand-set
  constants, so any consumer MUST carry the label returned by
  :func:`heuristic_status` (``HEURISTIC_NOT_VALIDATED``) alongside the number.
- :func:`confidence_score` returns a screening band, **not a calibrated
  probability**. It must always be published together with
  :func:`confidence_status` (``CONFIDENCE_NOT_CALIBRATED``).
- :func:`yield_loss_band` is an indicative band derived from the risk score
  alone. AGRIQ has no measured yield for these crops, so the number must be
  labelled ``YIELD_IMPACT_NOT_MEASURED`` (:func:`yield_loss_status`).
- The documented formulas live in ``docs/dashboard-heuristics.md``; they are
  reproduced there verbatim so the derivation is auditable.
"""
from __future__ import annotations

from typing import Any, Mapping

from ...core.constants import (
    TOKEN_CONFIDENCE_NOT_CALIBRATED,
    TOKEN_HEURISTIC_NOT_VALIDATED,
    TOKEN_YIELD_IMPACT_NOT_MEASURED,
)
from ..catalogs.districts import (
    COASTAL_DISTRICTS,
    HIGHLAND_DISTRICTS,
    WESTERN_DISTRICTS,
)
from .adjustments import field_condition_adjustment, growth_stage_adjustment


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    """Clamp ``value`` into [low, high]."""
    return max(low, min(high, value))


def risk_status(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 40:
        return "MODERATE"
    return "LOW"


def risk_color(score: float) -> str:
    if score >= 80:
        return "red"
    if score >= 60:
        return "orange"
    if score >= 40:
        return "yellow"
    return "green"


def urgency(score: float) -> str:
    if score >= 80:
        return "Inspect today"
    if score >= 60:
        return "Inspect within 24 hours"
    if score >= 40:
        return "Monitor for 3 days"
    return "Normal monitoring"


def component_scores(
    crop: Mapping[str, Any],
    weather: Mapping[str, Any] | None,
    leafscan: Mapping[str, Any],
    district: str,
    growth_stage: str,
    field_condition: str,
) -> dict[str, float]:
    """Named, weighted risk components; the sum is the displayed score.

    When verified weather is unavailable (values None), the weather-driven
    components are omitted entirely — they are never filled with generated
    substitutes, and the displayed score covers only available evidence.
    """
    components: dict[str, float] = {}

    temp = weather.get("temp") if weather else None
    humidity = weather.get("humidity") if weather else None
    rain = weather.get("rain") if weather else None
    low, high = crop["ideal_temp"]

    if humidity is not None:
        components["Humidity"] = round(clamp((humidity - crop["humidity_risk"] + 20) * 1.35, 0, 28), 1)
    if rain is not None:
        components["Rainfall"] = round(clamp((rain / max(crop["rainfall_risk"], 1)) * 18, 0, 22), 1)
    if temp is not None:
        temp_gap = 0.0
        if temp < low:
            temp_gap = low - temp
        elif temp > high:
            temp_gap = temp - high
        components["Temperature"] = round(clamp(temp_gap * 4.2, 0, 18), 1)

    components["Crop Sensitivity"] = round(clamp(crop["sensitivity"] * 1.9, 4, 18), 1)

    district_component = 0.0
    if district in COASTAL_DISTRICTS and (humidity or 0) >= 78:
        district_component += 5
    if district in WESTERN_DISTRICTS and (temp or 0) >= 34:
        district_component += 4
    if district in HIGHLAND_DISTRICTS and (rain or 0) >= 12:
        district_component += 3
    if district_component:
        components["District Factor"] = round(clamp(district_component, 0, 8), 1)

    leaf_component = leafscan.get("evidence_score", 0) if leafscan.get("available") else 0
    stage_component = growth_stage_adjustment(growth_stage)
    field_component = field_condition_adjustment(field_condition)
    if leaf_component:
        components["Leaf Evidence"] = round(leaf_component, 1)
    if stage_component:
        components["Growth Stage"] = round(stage_component, 1)
    if field_component:
        components["Field Condition"] = round(field_component, 1)

    return components


def heuristic_status() -> str:
    """Label every rule-based score in this module (Phase 7 §3)."""
    return TOKEN_HEURISTIC_NOT_VALIDATED


def confidence_status() -> str:
    """The calibration status of :func:`confidence_score` (never calibrated)."""
    return TOKEN_CONFIDENCE_NOT_CALIBRATED


def yield_loss_status() -> str:
    """Why :func:`yield_loss_band` is not a measurement."""
    return TOKEN_YIELD_IMPACT_NOT_MEASURED


def crop_health(score: float, leafscan: Mapping[str, Any]) -> int:
    """Rule-based 18–96 index: ``100 - risk*0.58 - leafscan_penalty``.

    A heuristic indicator, not a measured crop-health value.
    """
    penalty = int(leafscan.get("evidence_score", 0) * 0.25) if leafscan.get("available") else 0
    return int(clamp(100 - (score * 0.58) - penalty, 18, 96))


def productivity_score(score: float, weather: Mapping[str, Any] | None, growth_stage: str) -> int:
    """Rule-based 20–97 index: ``100 - risk*0.52`` minus documented deductions.

    Deductions: −5 when humidity > 82%, −6 when rain > 24 mm, −3 at a
    flowering/fruiting stage. A heuristic indicator, not a yield forecast.
    """
    score_value = 100 - int(score * 0.52)
    humidity = weather.get("humidity") if weather else None
    rain = weather.get("rain") if weather else None
    if humidity is not None and humidity > 82:
        score_value -= 5
    if rain is not None and rain > 24:
        score_value -= 6
    if "flower" in (growth_stage or "").lower() or "fruit" in (growth_stage or "").lower():
        score_value -= 3
    return int(clamp(score_value, 20, 97))


def yield_loss_band(score: float) -> str:
    """Indicative untreated-loss band: ``low = max(2, score*0.12)``,
    ``high = min(48, low + 8 + score*0.06)``.

    Derived from the risk score alone. It is NOT a measured or modelled yield
    loss — no yield data exists for these crops — so it is always published with
    :func:`yield_loss_status`.
    """
    low = max(2, int(score * 0.12))
    high = min(48, low + 8 + int(score * 0.06))
    return f"{low}% - {high}%"


def confidence_score(
    score: float,
    weather: Mapping[str, Any] | None,
    leafscan: Mapping[str, Any],
    components: Mapping[str, float],
) -> int:
    """Screening band 40–94 from a hand-set base of 64 with fixed adjustments.

    Weather present +9, LeafScan present +leafscan_confidence/10, score ≥ 60 +6,
    strongest component ≥ 18 +5, weather absent −12. This is a rule heuristic:
    it has never been calibrated against outcomes, so it MUST be published with
    :func:`confidence_status`, never as a bare "Confidence: NN%".
    """
    confidence = 64.0
    if weather and weather.get("available"):
        confidence += 9
    if leafscan.get("available"):
        confidence += int(leafscan.get("confidence", 0) / 10)
    if score >= 60:
        confidence += 6
    if components and max(components.values()) >= 18:
        confidence += 5
    if not (weather and weather.get("available")):
        confidence -= 12  # honestly lower confidence without verified weather
    return int(clamp(confidence, 40, 94))


__all__ = [
    "clamp",
    "risk_status",
    "risk_color",
    "urgency",
    "component_scores",
    "crop_health",
    "productivity_score",
    "yield_loss_band",
    "confidence_score",
    "confidence_status",
    "yield_loss_status",
    "heuristic_status",
]
