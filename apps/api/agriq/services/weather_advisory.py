"""Weather advisory service: console + risk-linked forecast rows.

Bridges the Open-Meteo integration and the risk engine. Provider state is
passed through verbatim: live data is labelled LIVE, unavailable data shows
the canonical unavailable message — a generated value is never substituted.
"""
from __future__ import annotations

from typing import Any, Mapping

from ..domain.risk.scoring import (
    clamp,
    component_scores,
    risk_color,
    risk_status,
)


def build_weather_console(
    district: str,
    crop: Mapping[str, Any],
    weather: Mapping[str, Any],
    forecast: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Weather console payload rendered by the dashboard."""
    if not weather.get("available"):
        return {
            "district": district,
            "available": False,
            "live_badge": "UNAVAILABLE",
            "message": weather.get("message", "Verified data is currently unavailable."),
            "reason": weather.get("reason"),
            "source_note": (
                "Weather comes live from Open-Meteo. The provider could not be reached, "
                "so no weather values are shown right now — nothing is estimated."
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

    return {
        "district": district,
        "available": True,
        "live_badge": "LIVE SYNC",
        "updated_at": weather.get("retrieved_at"),
        "provider_observed_at": weather.get("provider_observed_at"),
        "message": None,
        "source_note": "Live values are synced from Open-Meteo for the registered field coordinates. Forecast rows are provider forecasts, not on-field sensor readings.",
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
