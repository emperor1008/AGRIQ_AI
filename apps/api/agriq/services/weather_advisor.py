"""Weather-aware operational advisor (Phase 2 §9).

Turns verified Open-Meteo data for the field's real coordinates into
operational guidance families:

- Rain before irrigation (avoid unnecessary irrigation)
- Rain/wind before spraying (unsafe spray window)
- Heat during field operations
- Humidity as disease-conducive context (never a diagnosis)
- Heavy rainfall and drainage

Every output carries the provider, coordinates, freshness and horizon.
Weather is always treated as forecast-model output, never a farm sensor
reading, and weather alone never confirms a pest or disease.
"""
from __future__ import annotations

from typing import Any, Optional

from ..domain.advisory.recommendation import (
    ConfidenceResult,
    EvidenceItem,
    Recommendation,
    compute_confidence,
)
from ..domain.advisory.evidence import crop_cycle_evidence, weather_evidence

# Wind thresholds (km/h) used as *conservative operational* heuristics —
# they are stated as such and are not presented as regulatory limits.
WIND_UNSAFE_SPRAY_KMH = 15.0
HEAVY_RAIN_MM = 20.0
HEAT_STRESS_C = 35.0


def _has_forecast(weather: dict[str, Any]) -> bool:
    return bool(weather.get("available"))


def build_weather_recommendation(
    context: dict[str, Any],
    weather: Optional[dict[str, Any]],
    *,
    intent_type: str = "weather_rainfall",
) -> Recommendation:
    """Weather-window recommendation from live/stale provider data.

    When weather is unavailable the recommendation is an explicit
    unavailable-state message — never a seasonal assumption.
    """
    evidence: list[EvidenceItem] = []
    weather_item = weather_evidence(weather)
    if weather_item:
        evidence.append(weather_item)

    missing: list[str] = []
    if not _has_forecast(weather or {}):
        missing.append("live weather is currently unavailable")
        return Recommendation(
            recommendation_type=intent_type,
            action="Retry the weather check shortly; no field operation is advised on missing data.",
            reasons=["Live weather is currently unavailable."],
            evidence=evidence,
            confidence=ConfidenceResult(
                level="low", score=0.1,
                basis="No weather data is available; no weather-based guidance can be given.",
            ),
            requires_expert_confirmation=False,
            missing_information=missing,
        )

    temp = weather.get("temp")
    precipitation = weather.get("precipitation") or 0
    wind = weather.get("wind")
    reasons: list[str] = []
    actions: list[str] = []

    if precipitation and float(precipitation) >= HEAVY_RAIN_MM:
        actions.append("Check field drainage before any other operation")
        reasons.append(f"Heavy rainfall ({precipitation} mm) is shown by the provider")
    elif precipitation and float(precipitation) > 0:
        actions.append("Inspect field moisture before irrigating")
        reasons.append("Rain is forecast or occurring in the advisory window")
    else:
        actions.append("Inspect field moisture before irrigating")
        reasons.append("No rain is shown in the current provider window")

    if wind is not None and float(wind) >= WIND_UNSAFE_SPRAY_KMH:
        actions.append("Avoid spraying until wind drops to a calm window")
        reasons.append(f"Wind speed is {wind} km/h — above the safe spraying heuristic")
    if temp is not None and float(temp) >= HEAT_STRESS_C:
        actions.append("Schedule field work for cooler hours")
        reasons.append(f"Temperature is {temp}°C — heat-safe working hours are advised")

    cycle = context.get("crop_cycle") or {}
    stage = cycle.get("farmer_confirmed_stage") or cycle.get("calculated_stage")
    if stage:
        evidence.append(crop_cycle_evidence({
            "id": cycle.get("id"), "crop": cycle.get("crop"), "stage": stage,
            "sowing_date": cycle.get("sowing_date"), "updated_at": cycle.get("updated_at"),
        }))

    weather_fresh = bool(weather.get("available") and (weather.get("live") or (weather.get("cached") and not weather.get("stale"))))
    confidence = compute_confidence(
        context_completeness=0.6,
        weather_fresh=weather_fresh,
        weather_present=True,
        knowledge_top_score=0.0,
        knowledge_present=False,
        direct_observation=bool(context.get("recent_observations")),
        conflicting_evidence=False,
        missing_critical_inputs=0,
    )

    return Recommendation(
        recommendation_type=intent_type,
        action="; ".join(actions) if actions else "Monitor the weather and field condition",
        reasons=reasons,
        evidence=evidence,
        confidence=confidence,
        valid_until=_valid_until(weather_fresh),
        requires_expert_confirmation=False,
        missing_information=[],
    )


def _valid_until(weather_fresh: bool) -> Optional[str]:
    from datetime import timedelta
    from ..core.time import utc_now
    return (utc_now() + timedelta(hours=6 if weather_fresh else 12)).isoformat()


__all__ = ["build_weather_recommendation", "WIND_UNSAFE_SPRAY_KMH", "HEAVY_RAIN_MM", "HEAT_STRESS_C"]
