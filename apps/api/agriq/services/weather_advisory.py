"""Weather advisory service: console + risk-linked forecast rows.

Bridges the Open-Meteo integration and the risk engine. Provider state is
passed through verbatim: live data is labelled LIVE, unavailable data shows
the canonical unavailable message — a generated value is never substituted.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..core.constants import (
    STATE_CONFIGURATION_ERROR,
    STATE_DATA_SOURCE_ERROR,
    STATE_DATA_STALE,
    STATE_INVALID_LOCATION,
    STATE_OK,
    UNAVAILABLE_MESSAGE,
)
from ..domain.risk.scoring import (
    clamp,
    component_scores,
    risk_color,
    risk_status,
)

#: State-specific source note for the unavailable console: it names the actual
#: cause instead of blaming the provider for every outcome.
_UNAVAILABLE_SOURCE_NOTES = {
    STATE_DATA_SOURCE_ERROR: (
        "Weather comes live from Open-Meteo. The provider could not be reached just "
        "now, so no weather values are shown - nothing is estimated."
    ),
    STATE_INVALID_LOCATION: (
        "Weather comes live from Open-Meteo for a real location. No usable location is "
        "stored for this field yet, and AGRIQ does not guess one."
    ),
    STATE_DATA_STALE: (
        "Weather comes live from Open-Meteo. The last verified update is shown and "
        "marked stale; nothing is extrapolated from it."
    ),
    STATE_CONFIGURATION_ERROR: (
        "Weather comes live from Open-Meteo. This deployment cannot reach it with the "
        "current configuration, so no values are shown rather than estimated ones."
    ),
}


def build_weather_console(
    district: str,
    crop: Mapping[str, Any],
    weather: Mapping[str, Any],
    forecast: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Weather console payload rendered by the dashboard."""
    # A provider that answered without a single usable value is reported as the
    # unavailable state too: rendering "None°C" would present the absence of data
    # as a value.
    has_values = any(
        weather.get(key) is not None for key in ("temp", "humidity", "rain", "wind")
    )
    if not weather.get("available") or not has_values:
        state = weather.get("state") or STATE_DATA_SOURCE_ERROR
        return {
            "district": district,
            "available": False,
            "live_badge": "UNAVAILABLE",
            "message": weather.get("message", UNAVAILABLE_MESSAGE),
            "state": state,
            "state_message": weather.get("state_message") or UNAVAILABLE_MESSAGE,
            "reason": weather.get("reason"),
            "source_note": _UNAVAILABLE_SOURCE_NOTES.get(
                state,
                "Weather comes live from Open-Meteo. No weather values are shown right "
                "now - nothing is estimated.",
            ),
            "current": {"temp": None, "humidity": None, "rain": None, "wind": None,
                        "condition": None, "time": None},
            "hourly": [],
            "daily": [],
            "field_alert": "Weather data is unavailable. Base decisions on direct field observation today.",
            "disease_window": None,
            "irrigation_note": None,
            "spray_window": None,
        }

    rain_alert = max([row.get("rain", 0) or 0 for row in forecast] + [weather.get("rain", 0) or 0])
    humidity_alert = weather.get("humidity", 0) or 0
    disease_name = crop["diseases"].split(",")[0].strip()
    crop_name = crop.get("name", "selected crop")

    if rain_alert >= 25 or humidity_alert >= crop.get("humidity_risk", 76):
        disease_window = f"High watch for {disease_name}: high humidity/rain can keep leaves wet and increase disease spread in {crop_name}."
        spray_window = "Avoid spraying during rain, strong wind, wet foliage or just before expected rainfall. Prefer calm dry hours after field confirmation."
        field_alert = "Weather is favourable for disease spread. Scout lower leaves, stem base and new growth more frequently."
    elif (weather.get("wind", 0) or 0) > 22:
        disease_window = "Wind may reduce spray accuracy and can increase physical crop stress. Pest movement may also be higher in exposed fields."
        spray_window = "Postpone spray during windy hours and follow label safety guidance."
        field_alert = "Wind-sensitive field operation alert. Avoid drift-prone spray operations."
    else:
        disease_window = "No strong weather-driven disease window right now, but continue routine scouting because field microclimate may differ."
        spray_window = "Normal preventive care window; avoid unnecessary chemical use without symptoms or threshold-based need."
        field_alert = "Weather risk is manageable at the moment. Maintain observation and basic sanitation."

    irrigation_note = (
        "Improve drainage and avoid standing water; excess water can increase root stress and disease pressure."
        if (weather.get("rain", 0) or 0) > 8 or rain_alert > 20
        else "Maintain balanced irrigation based on crop stage and soil moisture; do not over-irrigate."
    )
    soil_water_note = (
        "Soil and water advice is general. For exact fertilizer and irrigation scheduling, use soil test, "
        "crop stage, field moisture and local KVK/agriculture department recommendation."
    )

    stale = bool(weather.get("stale")) or weather.get("state") == STATE_DATA_STALE
    location_note = (
        " Values are for the district administrative centre, not exact field coordinates."
        if weather.get("location_source") == "district_centre"
        else " Values are for the registered field coordinates."
    )
    return {
        "district": district,
        "available": True,
        "live_badge": "STALE" if stale else "LIVE SYNC",
        "state": weather.get("state") or STATE_OK,
        "state_message": weather.get("state_message"),
        "stale": stale,
        "location_source": weather.get("location_source"),
        "freshness": weather.get("freshness"),
        "updated_at": weather.get("retrieved_at"),
        "provider_observed_at": weather.get("provider_observed_at"),
        "message": None,
        "source_note": (
            "Live values are synced from Open-Meteo." + location_note + " Forecast rows are "
            "provider forecasts, not on-field sensor readings."
        ),
        "soil_water_note": soil_water_note,
        "current": {
            "temp": weather.get("temp"),
            "humidity": weather.get("humidity"),
            "rain": weather.get("rain"),
            "wind": weather.get("wind"),
            "condition": weather.get("condition"),
            "time": weather.get("provider_observed_at"),
        },
        "hourly": list(weather.get("hourly", []))[:12],
        "daily": list(weather.get("daily", []))[:7],
        "field_alert": field_alert,
        "disease_window": disease_window,
        "irrigation_note": irrigation_note,
        "spray_window": spray_window,
    }


def forecast_for(
    crop: Mapping[str, Any],
    district: str,
    weather: Mapping[str, Any],
    growth_stage: str,
    field_condition: str,
) -> list[dict[str, Any]]:
    """7-day risk-linked forecast rows for the dashboard card."""
    rows = []
    for item in weather.get("daily", []) or []:
        item_weather = {
            "temp": (item.get("temp_max") or 0 + item.get("temp_min") or 0) / 2
            if item.get("temp_max") is not None and item.get("temp_min") is not None
            else weather.get("temp"),
            "humidity": weather.get("humidity"),
            "rain": item.get("rain") or 0,
        }
        if item_weather["temp"] is None:
            continue
        comps = component_scores(
            crop, item_weather, {"available": False, "evidence_score": 0}, district, growth_stage, field_condition
        )
        score = int(clamp(sum(comps.values()), 0, 96))
        rows.append({
            "day": item.get("day"),
            "temp": item_weather["temp"],
            "humidity": weather.get("humidity"),
            "rain": item.get("rain"),
            "risk": score,
            "status": risk_status(score),
            "color": risk_color(score),
        })
    return rows


__all__ = ["build_weather_console", "forecast_for"]
