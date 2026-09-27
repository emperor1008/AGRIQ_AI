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

from ...core.constants import (
    OPEN_METEO_FORECAST_URL,
    PROVIDER_OPEN_METEO,
    REASON_INVALID_COORDINATES,
    REASON_NO_LOCATION,
    REASON_PROVIDER_HTTP_ERROR,
    REASON_PROVIDER_MALFORMED_RESPONSE,
    REASON_PROVIDER_REQUEST_FAILED,
    REASON_PROVIDER_TIMEOUT,
    STATE_DATA_SOURCE_ERROR,
    STATE_DATA_UNAVAILABLE,
    STATE_INVALID_LOCATION,
    STATE_MESSAGES,
    STATE_OK,
    UNAVAILABLE_MESSAGE,
)
from ...core.logging import get_logger
from ...core.time import as_utc, iso_utc, utc_now

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


#: Failure reason → machine-readable provider state (single mapping, shared by
#: every consumer so a UI never has to infer the cause from prose).
_FAILURE_STATE: "dict[str, str]" = {
    REASON_PROVIDER_TIMEOUT: STATE_DATA_SOURCE_ERROR,
    REASON_PROVIDER_HTTP_ERROR: STATE_DATA_SOURCE_ERROR,
    REASON_PROVIDER_MALFORMED_RESPONSE: STATE_DATA_SOURCE_ERROR,
    REASON_PROVIDER_REQUEST_FAILED: STATE_DATA_SOURCE_ERROR,
    REASON_NO_LOCATION: STATE_INVALID_LOCATION,
    REASON_INVALID_COORDINATES: STATE_INVALID_LOCATION,
}


def state_for_reason(reason: str | None) -> str:
    """Map a failure reason to its provider state (never to a value)."""
    return _FAILURE_STATE.get(reason or "", STATE_DATA_UNAVAILABLE)


def validate_coordinates(latitude: Any, longitude: Any) -> str | None:
    """Return a failure reason when coordinates cannot be queried.

    Exact ``0,0`` is treated as *not set*: it is the classic placeholder that
    leaked from an empty form, no AGRIQ deployment region lies there, and
    querying it would silently answer for the wrong place.
    """
    if latitude is None or longitude is None:
        return REASON_NO_LOCATION
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return REASON_INVALID_COORDINATES
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        return REASON_INVALID_COORDINATES
    if abs(lat) < 1e-9 and abs(lon) < 1e-9:
        return REASON_INVALID_COORDINATES
    return None


def unavailable(reason: str, state: str = STATE_DATA_UNAVAILABLE) -> dict[str, Any]:
    """Canonical unavailable payload — never carries generated values.

    ``message`` stays the canonical sentence existing consumers assert on;
    ``state_message`` carries the cause-specific wording the UI renders.
    """
    return {
        "available": False,
        "live": False,
        "provider": PROVIDER_OPEN_METEO,
        "reason": reason,
        "state": state,
        "state_message": STATE_MESSAGES.get(state, UNAVAILABLE_MESSAGE),
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


def fetch_weather(
    latitude: Any,
    longitude: Any,
    *,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
    retries: int = MAX_RETRIES,
) -> dict[str, Any]:
    """Fetch live weather, ALWAYS returning a payload with an explicit state.

    Failures are classified (timeout / HTTP / malformed / network) and mapped to
    a machine-readable state — never to a value. Safe retry policy: at most one
    retry, and no retry on HTTP 4xx, where repeating the request cannot help.
    """
    problem = validate_coordinates(latitude, longitude)
    if problem is not None:
        return unavailable(problem, STATE_INVALID_LOCATION)

    params = {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "current": "temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,wind_speed_10m",
        "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability,precipitation,rain,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
        "timezone": "Asia/Kolkata",
        "forecast_days": 7,
    }
    reason = REASON_PROVIDER_REQUEST_FAILED
    attempts = max(0, retries) + 1
    for attempt in range(attempts):
        try:
            response = requests.get(OPEN_METEO_FORECAST_URL, params=params, timeout=timeout)
            response.raise_for_status()
            try:
                payload = response.json()
            except ValueError:
                reason = REASON_PROVIDER_MALFORMED_RESPONSE
                logger.warning("open_meteo_malformed_json attempt=%s", attempt + 1)
                payload = None
            if payload is not None:
                parsed = _parse_open_meteo(payload)
                if _has_no_payload_sections(payload):
                    reason = REASON_PROVIDER_MALFORMED_RESPONSE
                    logger.warning("open_meteo_empty_payload attempt=%s", attempt + 1)
                else:
                    logger.info(
                        "weather_retrieved provider=%s lat=%.3f lon=%.3f",
                        PROVIDER_OPEN_METEO, float(latitude), float(longitude),
                    )
                    return parsed
        except requests.Timeout:
            reason = REASON_PROVIDER_TIMEOUT
            logger.warning("open_meteo_timeout attempt=%s", attempt + 1)
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            reason = REASON_PROVIDER_HTTP_ERROR
            logger.warning("open_meteo_http_error status=%s attempt=%s", status, attempt + 1)
            if status is not None and 400 <= status < 500:
                break  # client error: retrying will not help
        except Exception as exc:
            reason = REASON_PROVIDER_REQUEST_FAILED
            logger.warning(
                "open_meteo_failed error=%s attempt=%s", type(exc).__name__, attempt + 1
            )
        if attempt < attempts - 1:
            time.sleep(0.5)
    logger.warning("weather_unavailable reason=%s", reason)
    return unavailable(reason, state_for_reason(reason))


def fetch_live_weather(
    latitude: float,
    longitude: float,
    *,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
    retries: int = MAX_RETRIES,
) -> dict[str, Any] | None:
    """Phase 1 contract kept intact: the payload, or ``None`` on any failure."""
    result = fetch_weather(latitude, longitude, timeout=timeout, retries=retries)
    return result if result.get("available") else None


def _has_no_payload_sections(payload: Mapping[str, Any]) -> bool:
    """True when a provider body carries no recognisable weather section.

    A sparse but real response (individual fields missing) is NOT malformed:
    those fields stay ``None`` and the payload is returned exactly as retrieved,
    so a missing value can never be mistaken for a fabricated one.
    """
    for section in ("current", "hourly", "daily"):
        value = payload.get(section)
        if isinstance(value, Mapping) and value:
            return False
    return True


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
        # Success carries the same shape as failure: every payload has a state,
        # so a consumer never has to infer health from the absence of a key.
        "state": STATE_OK,
        "state_message": None,
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


def get_weather(
    district: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    *,
    location_source: str | None = None,
) -> dict[str, Any]:
    """Hour-cached weather accessor with an explicit, classified state.

    Accepts a district name (resolved through the district catalogue, which holds
    real administrative-centre coordinates) or exact coordinates. Failure returns
    :func:`unavailable` with a machine-readable ``state`` — never a substitute.

    ``location_source`` records how the location was resolved (exact field
    coordinates, farm coordinates, or the district centre) so provenance never
    implies more precision than the data has.
    """
    if lat is None or lon is None:
        if not district:
            return unavailable(REASON_NO_LOCATION, STATE_INVALID_LOCATION)
        from ...domain.catalogs.districts import coordinates_for_exact

        # Exact match only: an unrecognised district must produce an explicit
        # INVALID_LOCATION state, never weather fetched for a different place.
        coordinates = coordinates_for_exact(district)
        if not coordinates:
            logger.warning("weather_location_unresolved district=%s", district)
            return unavailable(REASON_INVALID_COORDINATES, STATE_INVALID_LOCATION)
        lat, lon = coordinates
        location_source = location_source or "district_centre"

    problem = validate_coordinates(lat, lon)
    if problem is not None:
        return unavailable(problem, STATE_INVALID_LOCATION)

    cache_key = f"{round(float(lat), 3)}:{round(float(lon), 3)}"
    cached = _cache.get(cache_key)
    if cached is None:
        cached = fetch_weather(lat, lon)
        _cache[cache_key] = cached

    # Copy before stamping: two callers can resolve the SAME coordinates from
    # different places (exact field coordinates vs the district centre). Caching
    # the stamped payload would hand the second caller the first caller's
    # location basis, i.e. overstate how precise its location is.
    result = dict(cached)
    result["latitude"] = round(float(lat), 4)
    result["longitude"] = round(float(lon), 4)
    result["location_source"] = location_source or "coordinates"
    if not result.get("available"):
        result["state"] = state_for_reason(result.get("reason"))
        result["state_message"] = STATE_MESSAGES.get(result["state"], UNAVAILABLE_MESSAGE)
    return result


def freshness(payload: Mapping[str, Any], ttl_seconds: int) -> dict[str, Any]:
    """Freshness of a weather payload, from the canonical classifier.

    The age is computed from the REAL retrieval timestamp; a payload with no
    timestamp is reported as ``unavailable`` freshness, never as fresh.
    """
    from ...domain.risk_engine.freshness import classify

    if not payload.get("available"):
        return {"freshness_status": "unavailable", "age_seconds": None,
                "ttl_seconds": ttl_seconds, "is_stale": True}
    status = classify("weather", payload.get("provider_observed_at"), payload.get("retrieved_at"))
    age_seconds: int | None = None
    retrieved = payload.get("retrieved_at")
    if retrieved:
        try:
            from datetime import datetime

            age_seconds = max(0, int((utc_now() - as_utc(datetime.fromisoformat(str(retrieved)))
                                      ).total_seconds()))
        except (TypeError, ValueError):
            age_seconds = None
    return {
        "freshness_status": status,
        "age_seconds": age_seconds,
        "ttl_seconds": ttl_seconds,
        "is_stale": status in ("stale", "expired", "unavailable"),
    }


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
    "validate_coordinates",
    "state_for_reason",
    "fetch_weather",
    "fetch_live_weather",
    "get_weather",
    "freshness",
    "forecast_weather",
    "response_hash",
    "REQUEST_TIMEOUT_SECONDS",
    "MAX_RETRIES",
]
