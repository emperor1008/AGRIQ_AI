"""Request parsers for the farmer-data API (Phase 1).

Server-side validation only — every payload is cleaned, length-limited and
type-checked here so blueprints and services receive trustworthy values.
Missing/unknown soil values remain absent; nothing is defaulted or invented.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from ..core.exceptions import ValidationError
from ..core.text import clean_text
from ..models.farmer import CropCycle, FieldObservation

_MAX_NAME = 150
_MAX_LOCATION = 120
_MAX_LANGUAGE = 30
_MAX_UNIT = 20
_MAX_VARIETY = 100
_MAX_SEASON = 40
_MAX_CONDITION = 120
_MAX_SEVERITY = 30


def _text(payload: Mapping[str, Any], key: str, max_length: int) -> str | None:
    """Cleaned optional text; empty string becomes None (absent)."""
    value = payload.get(key)
    if value is None:
        return None
    cleaned = clean_text(str(value), max_length)
    return cleaned or None


def _number(payload: Mapping[str, Any], key: str, *, low: float, high: float) -> float | None:
    value = payload.get(key)
    if value in (None, ""):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError(f"{key.replace('_', ' ').title()} must be a number.")
    if not (low <= number <= high):
        raise ValidationError(f"{key.replace('_', ' ').title()} must be between {low:g} and {high:g}.")
    return number


def _date(value: Any, key: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValidationError(f"{key.replace('_', ' ').title()} must be a date (YYYY-MM-DD).")


def _lat_lon(payload: Mapping[str, Any]) -> tuple[float | None, float | None]:
    latitude = _number(payload, "latitude", low=-90, high=90)
    longitude = _number(payload, "longitude", low=-180, high=180)
    if (latitude is None) != (longitude is None):
        raise ValidationError("Provide both latitude and longitude, or leave both empty.")
    return latitude, longitude


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def parse_profile_payload(payload: Mapping[str, Any], partial: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {}
    full_name = _text(payload, "full_name", _MAX_NAME)
    if full_name or not partial:
        data["full_name"] = full_name
    language = _text(payload, "preferred_language", _MAX_LANGUAGE)
    if language or not partial:
        data["preferred_language"] = language
    if _text(payload, "state", _MAX_LOCATION) or not partial:
        data["state"] = _text(payload, "state", _MAX_LOCATION)
    if _text(payload, "district", _MAX_LOCATION) or not partial:
        data["district"] = _text(payload, "district", _MAX_LOCATION)
    if _text(payload, "village", _MAX_LOCATION) or not partial:
        data["village"] = _text(payload, "village", _MAX_LOCATION)
    consent = _text(payload, "consent_version", 20)
    if consent:
        data["consent_version"] = consent
        from ..core.time import utc_now

        data["consented_at"] = utc_now()
    return data


# ---------------------------------------------------------------------------
# Farms / fields
# ---------------------------------------------------------------------------

_AREA_UNITS = {"acre", "hectare", "bigha", "katha", "gunta", "cent"}
_OWNERSHIP_TYPES = {"owned", "leased", "shared", "customary"}

def parse_farm_payload(payload: Mapping[str, Any], partial: bool = False) -> dict[str, Any]:
    name = _text(payload, "name", _MAX_NAME)
    if not name and not partial:
        raise ValidationError("Farm name is required.")
    data: dict[str, Any] = {}
    if name:
        data["name"] = name
    for key in ("state", "district", "village"):
        value = _text(payload, key, _MAX_LOCATION)
        if value or not partial:
            data[key] = value
    latitude, longitude = _lat_lon(payload)
    if latitude is not None or not partial:
        data["latitude"] = latitude
    if longitude is not None or not partial:
        data["longitude"] = longitude
    total_area = _number(payload, "total_area", low=0, high=100000)
    if total_area is not None or not partial:
        data["total_area"] = total_area
    unit = _text(payload, "area_unit", _MAX_UNIT)
    if unit:
        if unit.lower() not in _AREA_UNITS:
            raise ValidationError("Area unit must be one of: " + ", ".join(sorted(_AREA_UNITS)) + ".")
        data["area_unit"] = unit.lower()
    elif not partial:
        data["area_unit"] = None
    ownership = _text(payload, "ownership_type", 40)
    if ownership:
        if ownership.lower() not in _OWNERSHIP_TYPES:
            raise ValidationError("Ownership must be one of: " + ", ".join(sorted(_OWNERSHIP_TYPES)) + ".")
        data["ownership_type"] = ownership.lower()
    elif not partial:
        data["ownership_type"] = None
    return data


def parse_field_payload(payload: Mapping[str, Any], partial: bool = False) -> dict[str, Any]:
    name = _text(payload, "name", _MAX_NAME)
    if not name and not partial:
        raise ValidationError("Field name is required.")
    data: dict[str, Any] = {}
    if name:
        data["name"] = name
    area = _number(payload, "area", low=0, high=100000)
    if area is not None or not partial:
        data["area"] = area
    unit = _text(payload, "area_unit", _MAX_UNIT)
    if unit:
        if unit.lower() not in _AREA_UNITS:
            raise ValidationError("Area unit must be one of: " + ", ".join(sorted(_AREA_UNITS)) + ".")
        data["area_unit"] = unit.lower()
    elif not partial:
        data["area_unit"] = None
    if _text(payload, "soil_type", 80) or not partial:
        data["soil_type"] = _text(payload, "soil_type", 80)
    if _text(payload, "irrigation_type", 80) or not partial:
        data["irrigation_type"] = _text(payload, "irrigation_type", 80)
    latitude, longitude = _lat_lon(payload)
    if latitude is not None or not partial:
        data["latitude"] = latitude
    if longitude is not None or not partial:
        data["longitude"] = longitude
    return data


# ---------------------------------------------------------------------------
# Soil tests
# ---------------------------------------------------------------------------

def parse_soil_test_payload(payload: Mapping[str, Any], document_path: str | None = None) -> dict[str, Any]:
    """Soil values are individually optional; missing stays unknown."""
    source_type = (_text(payload, "source_type", 40) or "farmer_entered").lower()
    allowed_sources = {"laboratory_report", "farmer_entered", "geospatial_dataset", "district_reference"}
    if source_type not in allowed_sources:
        raise ValidationError("Soil source type is not recognised.")
    data: dict[str, Any] = {
        "source_type": source_type,
        "tested_at": _date(payload.get("tested_at"), "tested_at"),
        "laboratory_name": _text(payload, "laboratory_name", _MAX_NAME),
        "report_reference": _text(payload, "report_reference", 150),
        "ph": _number(payload, "ph", low=0, high=14),
        "electrical_conductivity": _number(payload, "electrical_conductivity", low=0, high=20),
        "organic_carbon": _number(payload, "organic_carbon", low=0, high=10),
        "nitrogen": _number(payload, "nitrogen", low=0, high=2000),
        "phosphorus": _number(payload, "phosphorus", low=0, high=500),
        "potassium": _number(payload, "potassium", low=0, high=2000),
        "document_path": document_path,
    }
    if source_type == "laboratory_report" and not document_path and not data["report_reference"]:
        raise ValidationError(
            "A laboratory report needs the document or at least a report reference number."
        )
    if source_type == "district_reference":
        data["laboratory_name"] = None
    return data


# ---------------------------------------------------------------------------
# Crop cycles
# ---------------------------------------------------------------------------

def parse_crop_cycle_payload(payload: Mapping[str, Any], partial: bool = False) -> dict[str, Any]:
    crop_name = _text(payload, "crop_name", _MAX_NAME) or _text(payload, "crop", _MAX_NAME)
    if not crop_name and not partial:
        raise ValidationError("Crop name is required.")
    data: dict[str, Any] = {}
    if crop_name:
        data["crop_name"] = crop_name
    if _text(payload, "variety", _MAX_VARIETY) or not partial:
        data["variety"] = _text(payload, "variety", _MAX_VARIETY)
    season = _text(payload, "season", _MAX_SEASON)
    if season or not partial:
        data["season"] = season
    for key in ("sowing_date", "transplanting_date", "expected_harvest_date"):
        value = _date(payload.get(key), key)
        if value is not None or not partial:
            data[key] = value
    if partial:
        status = _text(payload, "status", 20)
        if status:
            if status not in CropCycle.STATUSES:
                raise ValidationError("Crop cycle status is not recognised.")
            data["status"] = status
        previous = _text(payload, "previous_crop", _MAX_VARIETY)
        if previous or "previous_crop" in payload:
            data["previous_crop"] = previous
    else:
        data["status"] = CropCycle.STATUS_ACTIVE
        data["previous_crop"] = _text(payload, "previous_crop", _MAX_VARIETY)
    return data


def parse_stage_confirmation(payload: Mapping[str, Any]) -> str:
    stage = _text(payload, "stage", 80) or _text(payload, "farmer_confirmed_stage", 80)
    if not stage:
        raise ValidationError("Select the current crop stage to confirm.")
    return stage


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------

def parse_observation_payload(payload: Mapping[str, Any], image_path: str | None = None) -> dict[str, Any]:
    observation_type = (_text(payload, "observation_type", 40) or FieldObservation.TYPE_GENERAL).lower()
    if observation_type not in FieldObservation.TYPES:
        raise ValidationError("Observation type is not recognised.")
    severity = _text(payload, "farmer_reported_severity", _MAX_SEVERITY)
    if severity and severity.lower() not in {"low", "moderate", "high", "severe"}:
        raise ValidationError("Severity must be low, moderate, high or severe.")
    data: dict[str, Any] = {
        "observation_type": observation_type,
        "field_condition": _text(payload, "field_condition", _MAX_CONDITION),
        "notes": _text(payload, "notes", 2000),
        "farmer_reported_severity": severity.lower() if severity else None,
        "image_path": image_path,
    }
    observed_raw = payload.get("observed_at")
    if observed_raw in (None, ""):
        from ..core.time import utc_now

        data["observed_at"] = utc_now()
    else:
        text = str(observed_raw).strip()
        parsed = None
        for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValidationError("Observation date/time is not valid.")
        data["observed_at"] = parsed
    latitude = _number(payload, "latitude", low=-90, high=90)
    longitude = _number(payload, "longitude", low=-180, high=180)
    if (latitude is None) != (longitude is None):
        raise ValidationError("Provide both latitude and longitude, or leave both empty.")
    data["latitude"] = latitude
    data["longitude"] = longitude
    return data


__all__ = [
    "parse_profile_payload",
    "parse_farm_payload",
    "parse_field_payload",
    "parse_soil_test_payload",
    "parse_crop_cycle_payload",
    "parse_stage_confirmation",
    "parse_observation_payload",
]
