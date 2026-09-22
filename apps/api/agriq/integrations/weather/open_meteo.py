"""Open-Meteo weather integration (Phase 1 real-data policy).

Only provider-returned values are used. When the provider fails (or is
unreachable within the timeout + one safe retry), the integration returns an
explicit **unavailable** result — the offline seasonal model that existed in
the prototype has been REMOVED from production execution. Synthetic weather
may exist only inside test fixtures (tests/unit, clearly named).
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Mapping

import requests
from cachetools import TTLCache

from ...core.constants import OPEN_METEO_FORECAST_URL, PROVIDER_OPEN_METEO
from ...core.logging import get_logger
from ...core.time import iso_utc

logger = get_logger("integrations.open_meteo")

_cache: "TTLCache[str, dict[str, Any]]" = TTLCache(maxsize=256, ttl=1800)

REQUEST_TIMEOUT_SECONDS = 8
MAX_RETRIES = 1  # one safe retry after the first failure


def weather_condition(code: Any) -> str:
    """Map a WMO weather code to text (provider-returned code only)."""
    from ...core.constants import WEATHER_CODE_TEXT

    try:
        return WEATHER_CODE_TEXT.get(int(code), "Changing weather")
    except (TypeError, ValueError):
        return "Changing weather"


def unavailable(reason: str) -> dict[str, Any]:
    """Canonical unavailable payload — never carries generated values."""
    return {
        "available": False,
        "live": False,
        "provider": PROVIDER_OPEN_METEO,
        "reason": reason,
        "message": "Verified data is currently unavailable.",
        "retrieved_at": None,
        "temp": None,
        "humidity": None,
        "rain": None,
        "precipitation": None,
        "wind": None,
        "condition": None,
        "weather_code": None,
        "hourly": [],
        "daily": [],
        "history": [],
    }


def fetch_live_weather(
    latitude: float,
    longitude: float,
    *,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
    retries: int = MAX_RETRIES,
) -> dict[str, Any] | None:
    """Fetch live weather for exact coordinates. None on failure.

    Safe retry policy: at most one retry after a failure, no retry on HTTP
    4xx (client errors would only repeat the same mistake).
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,wind_speed_10m",
        "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,rain,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
        "timezone": "Asia/Kolkata",
        "forecast_days": 7,
    }
    attempts = max(0, retries) + 1
    for attempt in range(attempts):
        try:
            response = requests.get(OPEN_METEO_FORECAST_URL, params=params, timeout=timeout)
            response.raise_for_status()
            return _parse_open_meteo(response.json())
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            logger.warning("open_meteo_http_error status=%s attempt=%s", status, attempt + 1)
            if status is not None and 400 <= status < 500:
                return None  # client error: retrying will not help
        except Exception as exc:
            logger.warning(
                "open_meteo_failed error=%s attempt=%s", type(exc).__name__, attempt + 1
            )
        if attempt < attempts - 1:
            time.sleep(0.5)
    return None


def _parse_open_meteo(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Parse a provider payload. Missing provider fields stay None/absent."""
    current = payload.get("current", {}) or {}
    hourly = payload.get("hourly", {}) or {}
    daily = payload.get("daily", {}) or {}

    current_time = str(current.get("time", "")) or None

    hourly_times = hourly.get("time", []) or []
    start_index = 0
    if current_time and current_time in hourly_times:
        start_index = hourly_times.index(current_time)

    hourly_rows: list[dict[str, Any]] = []
    for idx in range(start_index, min(start_index + 12, len(hourly_times))):
        code = hourly.get("weather_code", [None] * len(hourly_times))[idx]
        time_value = hourly_times[idx]
        label = time_value[-5:] if "T" in time_value else time_value

        def _at(key: str) -> Any:
            series = hourly.get(key) or []
            return series[idx] if idx < len(series) else None

        hourly_rows.append({
            "time": label,
            "temp": _round(_at("temperature_2m")),
            "humidity": _round(_at("relative_humidity_2m")),
            "rain": _round(_at("rain")),
            "pop": int(_at("precipitation_probability") or 0),
            "wind": _round(_at("wind_speed_10m")),
            "condition": weather_condition(code),
        })

    daily_times = daily.get("time", []) or []
    daily_rows: list[dict[str, Any]] = []
    for idx, day in enumerate(daily_times[:7]):
        code = daily.get("weather_code", [None] * len(daily_times))[idx]

        def _day(key: str) -> Any:
            series = daily.get(key) or []
            return series[idx] if idx < len(series) else None

        daily_rows.append({
            "day": day,
            "temp_max": _round(_day("temperature_2m_max")),
            "temp_min": _round(_day("temperature_2m_min")),
            "rain": _round(_day("precipitation_sum")),
            "pop": int(_day("precipitation_probability_max") or 0),
            "wind": _round(_day("wind_speed_10m_max")),
            "condition": weather_condition(code),
        })

    code = current.get("weather_code")
    rain_value = current.get("rain")
    precipitation_value = current.get("precipitation")

    return {
        "available": True,
        "live": True,
        "provider": PROVIDER_OPEN_METEO,
        "reason": None,
        "provider_observed_at": current_time,
        "retrieved_at": iso_utc(),
        "temp": _round(current.get("temperature_2m")),
        "humidity": _round(current.get("relative_humidity_2m")),
        "rain": _round(rain_value if rain_value is not None else precipitation_value),
        "precipitation": _round(precipitation_value),
        "wind": _round(current.get("wind_speed_10m")),
        "condition": weather_condition(code) if code is not None else None,
        "weather_code": int(code) if str(code or "").isdigit() else code,
        "hourly": hourly_rows,
        "daily": daily_rows,
        "history": daily_rows,
    }


def _round(value: Any) -> float | None:
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def get_weather(district: str | None = None, lat: float | None = None, lon: float | None = None) -> dict[str, Any]:
    """Hour-cached weather accessor with explicit unavailable state.

    Accepts district name (catalogue coordinates) or exact coordinates.
    Failure returns :func:`unavailable` — never a generated substitute.
    """
    if lat is None or lon is None:
        if not district:
            return unavailable("no_location")
        from ...domain.catalogs.districts import coordinates_for

        lat, lon = coordinates_for(district)
    cache_key = f"{round(lat, 3)}:{round(lon, 3)}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    live = fetch_live_weather(lat, lon)
    result = live if live is not None else unavailable("provider_request_failed")
    _cache[cache_key] = result
    return result


def forecast_weather(weather: Mapping[str, Any]) -> list[dict[str, Any]]:
    """7-day forecast rows derived from provider daily data only."""
    rows: list[dict[str, Any]] = []
    for item in weather.get("daily", []) or []:
        try:
            avg_temp = round((float(item["temp_max"]) + float(item["temp_min"])) / 2, 1)
        except (TypeError, ValueError, KeyError):
            avg_temp = None
        rows.append({
            "day": item.get("day"),
            "temp": avg_temp,
            "humidity": weather.get("humidity"),
            "rain": item.get("rain"),
            "wind": item.get("wind"),
            "pop": item.get("pop", 0),
            "condition": item.get("condition", "Changing weather"),
        })
    return rows


def response_hash(payload: Mapping[str, Any]) -> str:
    """Stable hash of a raw provider payload for snapshot de-duplication."""
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "weather_condition",
    "unavailable",
    "fetch_live_weather",
    "get_weather",
    "forecast_weather",
    "response_hash",
    "REQUEST_TIMEOUT_SECONDS",
    "MAX_RETRIES",
]
