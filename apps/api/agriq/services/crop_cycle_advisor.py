"""Crop-cycle advisor service (Phase 2 §10).

Turns the verified farmer context (active crop cycle, stage, soil, weather)
into a stage-aware advisory with evidence. This service composes the domain
stage engine with real records only — every "possible action" is an action
family, never an exact quantity.
"""
from __future__ import annotations

from typing import Any, Optional

from ..core.logging import get_logger
from ..domain.advisory.crop_stage import stage_advisory
from ..domain.advisory.recommendation import (
    ConfidenceResult,
    EvidenceItem,
    Recommendation,
    compute_confidence,
)
from ..domain.advisory.evidence import (
    crop_cycle_evidence,
    knowledge_evidence,
    observation_evidence,
    soil_test_evidence,
    weather_evidence,
)

logger = get_logger("services.crop_cycle_advisor")


def build_stage_recommendation(
    context: dict[str, Any],
    weather: Optional[dict[str, Any]],
    retrieval: Optional[Any] = None,
    *,
    intent_type: str = "crop_care",
    focus_action: Optional[str] = None,
) -> Recommendation:
    """Build a stage-aware recommendation from verified context.

    ``focus_action`` narrows the action to one item (e.g. irrigation intent
    selects "Inspect field moisture before irrigating") when present in the
    stage engine's action list.
    """
    cycle = context.get("crop_cycle") or {}
    field = context.get("field") or {}
    stage_key = cycle.get("calculated_stage") or cycle.get("farmer_confirmed_stage")
    advisory = stage_advisory(stage_key, cycle.get("crop"))

    actions = advisory.possible_actions
    action = focus_action if focus_action in actions else (actions[0] if actions else "Record a field observation in AGRIQ")

    evidence: list[EvidenceItem] = []
    weather_item = weather_evidence(weather)
    if weather_item:
        evidence.append(weather_item)
    evidence.append(crop_cycle_evidence({
        "id": cycle.get("id"), "crop": cycle.get("crop"), "stage": advisory.stage,
        "sowing_date": cycle.get("sowing_date"), "updated_at": cycle.get("updated_at"),
    }))
    if context.get("recent_observations"):
        first = context["recent_observations"][0]
        evidence.append(observation_evidence(first))
    soil = context.get("soil") or {}
    soil_item = soil_test_evidence(soil) if soil.get("available") else None
    if soil_item:
        evidence.append(soil_item)
    if retrieval is not None and getattr(retrieval, "available", False):
        for passage in retrieval.passages[:1]:
            evidence.append(knowledge_evidence(passage.to_dict()))

    # Missing information: unknown stage, unconfirmed stage, missing soil test.
    missing = list(advisory.missing_information)
    if not stage_key:
        missing.append("crop stage (not calculated and not confirmed)")
    elif not cycle.get("farmer_confirmed_stage"):
        missing.append("farmer stage confirmation")
    if not (context.get("soil") or {}).get("available"):
        missing.append("no verified soil-test value has been recorded")

    weather_fresh = bool(weather and weather.get("available") and (weather.get("live") or weather.get("cached")) and not weather.get("stale"))
    weather_present = bool(weather and weather.get("available"))
    top_score = retrieval.top_score if retrieval is not None and getattr(retrieval, "available", False) else 0.0
    confidence = compute_confidence(
        context_completeness=_context_completeness(context),
        weather_fresh=weather_fresh,
        weather_present=weather_present,
        knowledge_top_score=top_score,
        knowledge_present=bool(retrieval is not None and getattr(retrieval, "available", False)),
        direct_observation=bool(context.get("recent_observations")),
        conflicting_evidence=False,
        missing_critical_inputs=len(missing),
    )

    recommendation_type = intent_type if intent_type != "general_agriculture" else "crop_care"
    return Recommendation(
        recommendation_type=recommendation_type,
        action=action,
        reasons=_stage_reasons(advisory, weather, context),
        evidence=evidence,
        confidence=confidence,
        valid_until=_valid_until(weather_fresh),
        requires_expert_confirmation=confidence.level == "low",
        missing_information=missing,
    )


def _stage_reasons(advisory, weather: Optional[dict[str, Any]], context: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    cycle = context.get("crop_cycle") or {}
    stage_label = advisory.stage
    if cycle.get("farmer_confirmed_stage"):
        reasons.append(f"The crop is at the farmer-confirmed {stage_label} stage")
    elif stage_key := (cycle.get("calculated_stage")):
        reasons.append(f"The crop is at the calculated {stage_label} stage (farmer confirmation pending)")
    else:
        reasons.append("The crop stage is not confirmed yet")
    if weather and weather.get("available"):
        if weather.get("precipitation") not in (None, 0):
            reasons.append("Rain is forecast or occurring in the advisory window")
        else:
            reasons.append(f"Current weather shows {weather.get('temp')}°C with {weather.get('humidity')}% humidity")
    else:
        reasons.append("Live weather is currently unavailable")
    soil = context.get("soil") or {}
    if not soil.get("available"):
        reasons.append("No verified soil-test value has been recorded")
    return reasons


def _context_completeness(context: dict[str, Any]) -> float:
    """Fraction of key verified-context dimensions present."""
    # Sections may be None (e.g. no active crop cycle) — normalise first.
    cycle = context.get("crop_cycle") or {}
    checks = [
        bool(context.get("farmer")),
        bool(context.get("farm")),
        bool(context.get("field")),
        bool(cycle.get("crop")),
        bool(cycle.get("farmer_confirmed_stage") or cycle.get("calculated_stage")),
        bool((context.get("soil") or {}).get("available")),
        bool((context.get("weather") or {}).get("available")),
    ]
    return sum(1.0 for c in checks if c) / len(checks)


def _valid_until(weather_fresh: bool) -> Optional[str]:
    from ..core.time import utc_now
    from datetime import timedelta
    # Advisory validity: one weather TTL when fresh, otherwise same-day.
    hours = 6 if weather_fresh else 12
    return (utc_now() + timedelta(hours=hours)).isoformat()


__all__ = ["build_stage_recommendation"]
