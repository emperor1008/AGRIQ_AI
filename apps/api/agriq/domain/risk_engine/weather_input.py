"""Weather-gathering helper shared by risk analyzers (Phase 5).

Fetches field weather through the existing Phase 1 weather service
(snapshot-backed, provenance-preserving) and additionally requests the
Open-Meteo forecast rows the risk engine needs (heavy rain, heat, humidity
windows). Forecast rows carry their own provider timestamps and are always
labelled forecast-model output, never sensor readings.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from ...core.time import iso_utc
from .freshness import classify


def gather(weather_payload: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """Normalise a weather payload (snapshot dict or live parse) for analyzers.

    Returns None when weather is unavailable (caller must produce an honest
    data_unavailable assessment). Forecast data is labelled explicitly.
    """
    if not weather_payload or not weather_payload.get("available"):
        return None

    observed_at = weather_payload.get("provider_observed_at")
    retrieved_at = weather_payload.get("retrieved_at") or iso_utc()
    fresh = classify("weather", observed_at, retrieved_at)

    daily = weather_payload.get("daily") or []
    hourly = weather_payload.get("hourly") or []

    return {
        "provider": weather_payload.get("provider") or "Open-Meteo",
        "observed_at": observed_at,
        "retrieved_at": retrieved_at,
        "freshness": fresh,
        "is_forecast": bool(weather_payload.get("live") is False and weather_payload.get("stale")),
        "temp": weather_payload.get("temp"),
        "humidity": weather_payload.get("humidity"),
        "rain": weather_payload.get("rain"),
        "precipitation": weather_payload.get("precipitation"),
        "wind": weather_payload.get("wind"),
        "condition": weather_payload.get("condition"),
        "hourly": list(hourly) if isinstance(hourly, list) else [],
        "daily": list(daily) if isinstance(daily, list) else [],
    }


def daily_rain(weather: Mapping[str, Any], days: int) -> tuple[list[float], int]:
    """Per-day forecast rainfall (mm) for the next ``days`` days.

    Returns ``(values, days_with_data)``. A provider gap is a gap — it is
    skipped, never coerced to 0 mm (real-data policy §1).
    """
    values: list[float] = []
    days_with_data = 0
    for row in (weather.get("daily") or [])[:days]:
        rain = row.get("rain")
        if rain is None:
            continue
        try:
            values.append(float(rain))
            days_with_data += 1
        except (TypeError, ValueError):
            continue
    return values, days_with_data


def hourly_humidity(weather: Mapping[str, Any]) -> list[float]:
    """Hourly humidity series (%), skipping provider gaps."""
    values: list[float] = []
    for row in (weather.get("hourly") or []):
        humidity = row.get("humidity")
        try:
            values.append(float(humidity))
        except (TypeError, ValueError):
            continue
    return values


def observation_evidence(weather: Mapping[str, Any], detail: str) -> dict[str, Any]:
    """Evidence block for the current weather observation."""
    return {
        "type": "weather_observation",
        "source": weather.get("provider", "Open-Meteo"),
        "observed_at": weather.get("observed_at"),
        "retrieved_at": weather.get("retrieved_at"),
        "freshness": weather.get("freshness", "unavailable"),
        "detail": detail,
    }


def forecast_evidence(weather: Mapping[str, Any], detail: str) -> dict[str, Any]:
    """Evidence block for forecast-model output (labelled as forecast)."""
    return {
        "type": "weather_forecast",
        "source": weather.get("provider", "Open-Meteo"),
        "observed_at": weather.get("observed_at"),
        "retrieved_at": weather.get("retrieved_at"),
        "freshness": weather.get("freshness", "unavailable"),
        "detail": detail,
    }


__all__ = ["gather", "daily_rain", "hourly_humidity", "observation_evidence", "forecast_evidence"]
