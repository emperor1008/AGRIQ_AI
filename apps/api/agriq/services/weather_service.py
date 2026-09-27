"""Weather service (Phase 1): verified weather for registered field coordinates.

Fetches from Open-Meteo using the exact field/farm coordinates, persists a
WeatherSnapshot row (provider, observation time, retrieval time, coordinates,
live flag, response hash) and de-duplicates snapshots using the raw response
hash so identical provider payloads are not stored repeatedly.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from ..core.constants import (
    REASON_NO_FIELD_COORDINATES,
    STATE_DATA_STALE,
    STATE_INVALID_LOCATION,
    STATE_OK,
)
from ..core.logging import get_logger
from ..core.time import as_utc, parse_provider_time, utc_now
from ..extensions import db
from ..integrations.weather import open_meteo
from ..models.farmer import WeatherSnapshot
from ..repositories.farmer_repository import FieldRepository

logger = get_logger("services.weather_service")

#: Weather enters the regression chain a district centre can legitimately answer
#: for, so a stored snapshot is always labelled with how the location resolved.
LOCATION_FIELD = "field_coordinates"
LOCATION_FARM = "farm_coordinates"
LOCATION_DISTRICT = "district_centre"


def _snapshot_to_dict(snapshot: WeatherSnapshot, is_cached: bool) -> dict[str, Any]:
    return {
        "available": True,
        "live": bool(snapshot.is_live) and not is_cached,
        "cached": is_cached,
        "state": STATE_OK,
        "state_message": None,
        "provider": snapshot.provider,
        "provider_observed_at": snapshot.provider_observed_at.isoformat() if snapshot.provider_observed_at else None,
        "retrieved_at": snapshot.retrieved_at.isoformat() if snapshot.retrieved_at else None,
        "latitude": snapshot.latitude,
        "longitude": snapshot.longitude,
        "temp": snapshot.temperature,
        "humidity": snapshot.humidity,
        "rain": snapshot.rain,
        "precipitation": snapshot.precipitation,
        "wind": snapshot.wind_speed,
        "weather_code": snapshot.weather_code,
        "condition": open_meteo.weather_condition(snapshot.weather_code) if snapshot.weather_code is not None else None,
        "message": None,
        "reason": None,
    }


def _ttl_seconds() -> int:
    from flask import current_app

    return int(current_app.config.get("WEATHER_SNAPSHOT_TTL_SECONDS", 1800))


def _with_freshness(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach the canonical freshness block (age from the real timestamps)."""
    payload["freshness"] = open_meteo.freshness(payload, _ttl_seconds())
    return payload


def get_district_weather(district: str | None) -> dict[str, Any]:
    """Live weather for a district's administrative centre.

    Used only when no exact field/farm coordinates exist. The district catalogue
    holds real administrative-centre coordinates, so this is a real provider
    lookup for a coarser location — and it says so, rather than implying field
    precision. No value is ever estimated for a missing location.
    """
    weather = open_meteo.get_weather(district, location_source=LOCATION_DISTRICT)
    if weather.get("available"):
        weather["cached"] = False
        weather["location_basis"] = (
            "District administrative centre from the AGRIQ district catalogue - a "
            "coarser location than exact field coordinates."
        )
    weather = _with_freshness(weather)
    return weather


def get_field_weather(field_id: int, profile_id: int) -> dict[str, Any]:
    """Verified weather for a field the caller owns, with snapshot persistence.

    Uses a fresh snapshot when the stored one is older than the TTL or missing;
    otherwise returns the stored snapshot marked ``cached=True``. When neither
    the field nor its farm carries coordinates the lookup falls back to the
    district administrative centre, which is labelled as such; with no usable
    location at all the result is the explicit ``INVALID_LOCATION`` state.
    """
    field = FieldRepository.get_owned(field_id, profile_id)
    if field is None:
        return open_meteo.unavailable("field_not_found", STATE_INVALID_LOCATION)

    ttl = _ttl_seconds()
    snapshot = _latest_snapshot(field.id)
    if snapshot is not None and snapshot.retrieved_at is not None:
        age = (utc_now().replace(tzinfo=None) - as_utc(snapshot.retrieved_at).replace(tzinfo=None)).total_seconds()
        if age < ttl:
            return _with_freshness(_snapshot_to_dict(snapshot, is_cached=True))

    coordinates = _resolve_coordinates(field)
    if coordinates is None:
        district = _field_district(field)
        if district:
            fallback = get_district_weather(district)
            if fallback.get("available"):
                fallback["snapshot_persisted"] = False
            return fallback
        return _with_freshness(
            open_meteo.unavailable(REASON_NO_FIELD_COORDINATES, STATE_INVALID_LOCATION)
        )

    lat, lon, source = coordinates
    weather = open_meteo.fetch_weather(lat, lon)
    if not weather.get("available"):
        # Serve the last stored snapshot as stale cache when the provider fails.
        if snapshot is not None:
            stale = _snapshot_to_dict(snapshot, is_cached=True)
            stale["live"] = False
            stale["cached"] = True
            stale["stale"] = True
            stale["state"] = STATE_DATA_STALE
            stale["state_message"] = (
                "The last verified update is shown and marked stale because the "
                "weather provider could not be reached now."
            )
            return _with_freshness(stale)
        return _with_freshness(weather)

    stored = _persist_snapshot(field, lat, lon, weather)
    payload = _snapshot_to_dict(stored, is_cached=False)
    payload["location_source"] = source
    return _with_freshness(payload)


def _resolve_coordinates(field) -> tuple[float, float, str] | None:
    """Best real coordinates for the field: exact first, then the farm's."""
    problem = open_meteo.validate_coordinates(field.latitude, field.longitude)
    if problem is None:
        return float(field.latitude), float(field.longitude), LOCATION_FIELD
    farm = field.farm
    if farm is not None:
        problem = open_meteo.validate_coordinates(farm.latitude, farm.longitude)
        if problem is None:
            return float(farm.latitude), float(farm.longitude), LOCATION_FARM
    return None


def _field_district(field) -> str | None:
    """The district documented on the field's farm (never guessed)."""
    farm = getattr(field, "farm", None)
    district = getattr(farm, "district", None) if farm is not None else None
    return str(district).strip() or None


def _latest_snapshot(field_id: int) -> Optional[WeatherSnapshot]:
    return db.session.execute(
        db.select(WeatherSnapshot)
        .where(WeatherSnapshot.field_id == field_id)
        .order_by(WeatherSnapshot.retrieved_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _parse_provider_observed(value: Any):
    """Open-Meteo returns naive IST wall time; convert to aware UTC."""
    if not value:
        return None
    text = str(value).strip()
    if "T" in text and len(text) == 16:
        text += ":00+05:30"  # requested timezone=Asia/Kolkata
    return parse_provider_time(text)


def _persist_snapshot(field, lat: float, lon: float, weather: Mapping[str, Any]) -> WeatherSnapshot:
    response_hash = open_meteo.response_hash({
        "temp": weather.get("temp"), "humidity": weather.get("humidity"),
        "rain": weather.get("rain"), "wind": weather.get("wind"),
        "code": weather.get("weather_code"), "observed": weather.get("provider_observed_at"),
    })
    latest = _latest_snapshot(field.id)
    if latest is not None and latest.raw_response_hash == response_hash and latest.is_live:
        # Identical provider payload; refresh retrieval time only.
        latest.retrieved_at = utc_now()
        db.session.commit()
        return latest

    snapshot = WeatherSnapshot(
        field_id=field.id,
        provider=weather.get("provider", "Open-Meteo"),
        provider_observed_at=_parse_provider_observed(weather.get("provider_observed_at")),
        retrieved_at=utc_now(),
        latitude=lat,
        longitude=lon,
        temperature=weather.get("temp"),
        humidity=weather.get("humidity"),
        precipitation=weather.get("precipitation"),
        rain=weather.get("rain"),
        wind_speed=weather.get("wind"),
        weather_code=weather.get("weather_code"),
        raw_response_hash=response_hash,
        is_live=True,
    )
    db.session.add(snapshot)
    db.session.commit()
    return snapshot


def record_snapshot_from_payload(field, payload: Mapping[str, Any]) -> Optional[WeatherSnapshot]:
    """Persist a snapshot from an already-parsed live payload (used by tests)."""
    return _persist_snapshot(field, float(payload["latitude"]), float(payload["longitude"]), payload)


__all__ = [
    "get_field_weather",
    "get_district_weather",
    "record_snapshot_from_payload",
    "LOCATION_FIELD",
    "LOCATION_FARM",
    "LOCATION_DISTRICT",
]
