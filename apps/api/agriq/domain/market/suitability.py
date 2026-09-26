"""Agronomic crop suitability from the existing catalogs (Phase 6 §5).

Every factor is a documented rule over data AGRIQ already curates, so a
suitability statement can always be traced to its source:

| Factor | Source |
| --- | --- |
| Temperature window | ``catalogs.crops`` ``ideal_temp`` (°C) |
| Humidity sensitivity | ``catalogs.crops`` ``humidity_risk`` (% RH) |
| Rainfall sensitivity | ``catalogs.crops`` ``rainfall_risk`` (mm) |
| Season | ``catalogs.crops`` ``season`` |
| Soil | ``catalogs.crops`` ``soil`` + district agro-climatic profile |
| Production belt | ``catalogs.districts`` curated ``main`` crops |
| Live conditions | verified weather (Open-Meteo) when available |

These are the project's curated agronomic reference points, **not** a
locally-calibrated yield model. Outcomes are therefore stated as
*favourable / caution / unfavourable / unknown* per factor rather than as a
single opaque score, and a factor whose input is missing is reported as
``unknown`` — never silently assumed to be fine.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from ..catalogs.crops import CROPS, resolve_crop
from ..catalogs.districts import profile_for

#: How much above/below the ideal window still counts as "caution" rather than
#: outright unfavourable (°C).
TEMPERATURE_TOLERANCE_C = 3.0

#: A season is "unknown" unless the catalog names it explicitly or the crop is
#: all-season/perennial.
_SEASON_ALIASES: Mapping[str, tuple[str, ...]] = {
    "kharif": ("kharif", "rainy", "monsoon"),
    "rabi": ("rabi", "winter"),
    "summer": ("summer", "zaid", "hot weather"),
}

_OUTCOME_FAVOURABLE = "favourable"
_OUTCOME_CAUTION = "caution"
_OUTCOME_UNFAVOURABLE = "unfavourable"
_OUTCOME_UNKNOWN = "unknown"


def _factor(name: str, outcome: str, observation: str, basis: str,
            source: str, value: Any = None, unit: str | None = None) -> dict[str, Any]:
    return {
        "factor": name,
        "outcome": outcome,
        "observation": observation,
        "basis": basis,
        "source": source,
        "value": value,
        "unit": unit,
    }


def _season_tokens(text: str) -> set[str]:
    return {token.strip().lower() for token in text.replace("(", " ").replace(")", " ").split("/")} | {
        text.strip().lower()
    }


def evaluate_season(catalog_season: str, requested_season: str | None) -> dict[str, Any]:
    """Match the farmer's season against the catalog's documented seasons."""
    source = "AGRIQ crop catalog (season field)"
    if not requested_season:
        return _factor(
            "season", _OUTCOME_UNKNOWN,
            "The season for this planting was not provided.",
            "A season must be known before suitability can be judged.",
            source,
        )
    catalog = (catalog_season or "").lower()
    requested = requested_season.strip().lower()
    if any(word in catalog for word in ("all season", "perennial", "annual")):
        return _factor(
            "season", _OUTCOME_FAVOURABLE,
            f"The catalog lists this crop as '{catalog_season}'.",
            "All-season / perennial crops are not season-restricted.",
            source, value=catalog_season,
        )
    tokens = _season_tokens(catalog)
    aliases = _SEASON_ALIASES.get(requested, (requested,))
    if tokens & set(aliases) or any(alias in catalog for alias in aliases):
        return _factor(
            "season", _OUTCOME_FAVOURABLE,
            f"Catalog season '{catalog_season}' covers the selected {requested_season} season.",
            "Documented crop calendar match.",
            source, value=catalog_season,
        )
    return _factor(
        "season", _OUTCOME_UNFAVOURABLE,
        f"Catalog season is '{catalog_season}', which does not cover {requested_season}.",
        "Documented crop calendar mismatch.",
        source, value=catalog_season,
    )


def evaluate_temperature(ideal: tuple[float, float], temp: float | None) -> dict[str, Any]:
    """Compare the verified current temperature with the catalog window."""
    source = "AGRIQ crop catalog (ideal_temp) + Open-Meteo observation"
    low, high = ideal
    if temp is None:
        return _factor(
            "temperature", _OUTCOME_UNKNOWN,
            f"Verified temperature is unavailable; the catalog window is {low}–{high} °C.",
            "No weather value was retrieved for this field.",
            source,
        )
    if low <= temp <= high:
        outcome = _OUTCOME_FAVOURABLE
        observation = f"{temp:.1f} °C is inside the catalog window {low}–{high} °C."
    elif (low - TEMPERATURE_TOLERANCE_C) <= temp <= (high + TEMPERATURE_TOLERANCE_C):
        outcome = _OUTCOME_CAUTION
        observation = (
            f"{temp:.1f} °C is just outside the catalog window {low}–{high} °C "
            f"(within {TEMPERATURE_TOLERANCE_C:.0f} °C)."
        )
    else:
        outcome = _OUTCOME_UNFAVOURABLE
        observation = f"{temp:.1f} °C is outside the catalog window {low}–{high} °C."
    return _factor(
        "temperature", outcome, observation,
        "Catalog ideal-temperature window with a 3 °C caution band.", source,
        value=temp, unit="°C",
    )


def evaluate_rainfall(rainfall_threshold: float, rain_mm: float | None) -> dict[str, Any]:
    """Compare recent/forecast rainfall with the catalog sensitivity threshold."""
    source = "AGRIQ crop catalog (rainfall_risk) + Open-Meteo"
    if rain_mm is None:
        return _factor(
            "rainfall", _OUTCOME_UNKNOWN,
            f"Rainfall is unavailable; the catalog sensitivity reference is {rainfall_threshold} mm.",
            "No rainfall value was retrieved for this field.",
            source,
        )
    if rain_mm <= rainfall_threshold:
        return _factor(
            "rainfall", _OUTCOME_FAVOURABLE,
            f"{rain_mm:.1f} mm is within the {rainfall_threshold} mm reference for this crop.",
            "Catalog rainfall sensitivity reference.", source, value=rain_mm, unit="mm",
        )
    return _factor(
        "rainfall", _OUTCOME_CAUTION,
        f"{rain_mm:.1f} mm exceeds the {rainfall_threshold} mm reference for this crop.",
        "Catalog rainfall sensitivity reference; excess moisture is a documented stress for this crop.",
        source, value=rain_mm, unit="mm",
    )


def evaluate_humidity(humidity_threshold: float, humidity: float | None) -> dict[str, Any]:
    """Compare verified humidity with the catalog disease-pressure reference."""
    source = "AGRIQ crop catalog (humidity_risk) + Open-Meteo observation"
    if humidity is None:
        return _factor(
            "humidity", _OUTCOME_UNKNOWN,
            f"Humidity is unavailable; the catalog reference is {humidity_threshold} %.",
            "No humidity value was retrieved for this field.", source,
        )
    if humidity < humidity_threshold:
        return _factor(
            "humidity", _OUTCOME_FAVOURABLE,
            f"{humidity:.0f} % is below the {humidity_threshold:.0f} % disease-pressure reference.",
            "Catalog humidity reference.", source, value=humidity, unit="%",
        )
    return _factor(
        "humidity", _OUTCOME_CAUTION,
        f"{humidity:.0f} % is at or above the {humidity_threshold:.0f} % disease-pressure reference.",
        "Catalog humidity reference; humid conditions favour the crop's documented diseases.",
        source, value=humidity, unit="%",
    )


def evaluate_soil(catalog_soil: str, district: str) -> dict[str, Any]:
    """Compare the crop's catalog soil requirement with the district profile."""
    source = "AGRIQ crop catalog (soil) + district agro-climatic profile"
    profile = profile_for(district)
    district_soil = str(profile.get("soil", "")).lower()
    catalog_soil_lower = (catalog_soil or "").lower()
    if not district_soil:
        return _factor(
            "soil", _OUTCOME_UNKNOWN,
            "No agro-climatic soil profile is recorded for this district.",
            "District profile missing.", source,
        )
    shared = {
        word for word in ("alluvial", "loam", "clay", "sandy", "laterite", "red", "black")
        if word in district_soil and word in catalog_soil_lower
    }
    if shared:
        return _factor(
            "soil", _OUTCOME_FAVOURABLE,
            f"District soil profile '{profile.get('soil')}' shares {', '.join(sorted(shared))} "
            f"with the crop's requirement '{catalog_soil}'.",
            "Curated district agro-climatic profile vs catalog requirement.",
            source, value=profile.get("soil"),
        )
    return _factor(
        "soil", _OUTCOME_CAUTION,
        f"District soil profile '{profile.get('soil')}' does not clearly match the crop "
        f"requirement '{catalog_soil}'.",
        "Textual soil comparison only — a soil test is required for a definite judgement.",
        source, value=profile.get("soil"),
    )


def evaluate_belt(crop_key: str, district: str) -> dict[str, Any]:
    """Whether the district's curated profile lists this crop as a main crop."""
    source = "AGRIQ district agro-climatic profile (main crops)"
    profile = profile_for(district)
    main = str(profile.get("main", "")).lower()
    if not main:
        return _factor(
            "production_belt", _OUTCOME_UNKNOWN,
            "No documented main-crop list for this district.",
            "District profile missing.", source,
        )
    profile_record, _ = resolve_crop(crop_key)
    names = {str(profile_record["name"]).lower(), crop_key.lower()}
    category = str(profile_record.get("category", "")).lower()
    if any(name and name in main for name in names) or (category and category in main):
        return _factor(
            "production_belt", _OUTCOME_FAVOURABLE,
            f"The {district} profile documents '{profile.get('main')}' as its main production.",
            "Curated district production profile.", source, value=profile.get("main"),
        )
    return _factor(
        "production_belt", _OUTCOME_CAUTION,
        f"The {district} profile documents '{profile.get('main')}' as its main production; "
        f"this crop is not listed.",
        "Absence from the curated list is not proof the crop fails here.",
        source, value=profile.get("main"),
    )


def _overall_status(factors: Iterable[Mapping[str, Any]]) -> str:
    """Status from factor outcomes, with the documented dominance rule."""
    outcomes = [f["outcome"] for f in factors]
    if any(o == _OUTCOME_UNFAVOURABLE for o in outcomes):
        return "unsuitable"
    if outcomes.count(_OUTCOME_UNKNOWN) >= 3:
        return "insufficient_data"
    if _OUTCOME_CAUTION in outcomes:
        return "marginal"
    if all(o == _OUTCOME_FAVOURABLE for o in outcomes):
        return "suitable"
    return "marginal"


def evaluate_crop(
    crop_key: str,
    *,
    district: str,
    season: str | None = None,
    weather: Mapping[str, Any] | None = None,
    rain_mm: float | None = None,
) -> dict[str, Any]:
    """Agronomic suitability of one crop for one district, with all evidence."""
    record, key = resolve_crop(crop_key)
    # ``resolve_crop`` returns a transparent generic profile for names AGRIQ does
    # not curate. That profile describes no specific crop, so it cannot support a
    # suitability verdict for one.
    catalog_known = key in CROPS and isinstance(CROPS.get(key), dict)
    conditions = weather if (weather and weather.get("available")) else None
    temp = conditions.get("temp") if conditions else None
    humidity = conditions.get("humidity") if conditions else None

    season_factor = (
        evaluate_season(str(record.get("season", "")), season)
        if catalog_known
        else _factor(
            "season", _OUTCOME_UNKNOWN,
            f"'{crop_key}' is not in the AGRIQ crop catalog, so no documented crop "
            "calendar is available for it.",
            "A crop with no documented agronomic profile is never judged unsuitable.",
            "AGRIQ crop catalog",
        )
    )

    factors = [
        season_factor,
        evaluate_temperature(tuple(record.get("ideal_temp", (0, 40))), temp),
        evaluate_rainfall(float(record.get("rainfall_risk", 0)), rain_mm),
        evaluate_humidity(float(record.get("humidity_risk", 0)), humidity),
        evaluate_soil(str(record.get("soil", "")), district),
        evaluate_belt(key, district),
    ]
    status = _overall_status(factors) if catalog_known else "insufficient_data"
    reasons = [
        f"{factor['factor'].replace('_', ' ').title()}: {factor['observation']}"
        for factor in factors
        if factor["outcome"] != _OUTCOME_UNKNOWN
    ]
    missing = [factor["factor"] for factor in factors if factor["outcome"] == _OUTCOME_UNKNOWN]

    return {
        "crop": key,
        "crop_name": record.get("name"),
        "crop_category": record.get("category"),
        "season": record.get("season"),
        "catalog_status": "documented" if catalog_known else "not_in_catalog",
        "recommendation_status": status,
        "limitation": (
            None if catalog_known else
            (
                f"'{crop_key}' has no documented agronomic profile in the AGRIQ catalog. The "
                "factor outcomes below come from the generic reference profile and cannot "
                "support a suitability verdict; consult a local agronomist before planting it."
            )
        ),
        "factors": factors,
        "reasons": reasons,
        "missing_information": missing,
        "supporting_evidence": [
            {
                "source": factor["source"],
                "factor": factor["factor"],
                "value": factor["value"],
                "unit": factor["unit"],
                "outcome": factor["outcome"],
            }
            for factor in factors
        ],
        "confidence": {
            "status": "not_calibrated",
            "basis": (
                "Agronomic suitability is a transparent rule assessment over curated catalogs; "
                "it is not a statistically calibrated probability and no percentage is claimed."
            ),
            "inputs_available": 6 - len(missing),
            "inputs_total": 6,
        },
        "requires_expert_confirmation": status in ("marginal", "unsuitable"),
    }


def candidate_crops(district: str, season: str | None = None) -> list[str]:
    """Catalog crop keys worth evaluating for a district/season.

    Selection is transparent: crops whose documented season matches (or that are
    all-season) come first, followed by the district's documented main crops.
    Crops outside both lists are still evaluable on request but are not proposed
    as candidates, so the option list is never padded with arbitrary names.
    """
    profile = profile_for(district)
    main = str(profile.get("main", "")).lower()
    belt: list[str] = []
    seasonal: list[str] = []
    for key, record in CROPS.items():
        if not isinstance(record, dict):
            continue
        name = str(record["name"]).lower()
        category = str(record.get("category", "")).lower()
        if name in main or category in main:
            # The district's own documented production comes first: a caller that
            # limits the option count must never lose the local main crop.
            belt.append(key)
            continue
        season_ok = True if not season else evaluate_season(
            str(record.get("season", "")), season
        )["outcome"] == _OUTCOME_FAVOURABLE
        if season_ok:
            seasonal.append(key)
    return belt + seasonal


__all__ = [
    "TEMPERATURE_TOLERANCE_C",
    "evaluate_crop",
    "evaluate_season",
    "evaluate_temperature",
    "evaluate_rainfall",
    "evaluate_humidity",
    "evaluate_soil",
    "evaluate_belt",
    "candidate_crops",
]
