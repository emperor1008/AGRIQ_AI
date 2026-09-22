"""Domain layer unit tests: catalogs, risk scoring, adjustments."""
from __future__ import annotations

from agriq.domain.catalogs.crops import crop_display_names, resolve_crop
from agriq.domain.catalogs.districts import DISTRICTS, coordinates_for, profile_for
from agriq.domain.catalogs.education import STUDENT_AREAS, STUDENT_DOMAIN_CONFIG
from agriq.domain.catalogs.pests import PEST_LIBRARY
from agriq.domain.catalogs.diseases import DISEASE_LIBRARY
from agriq.domain.catalogs.soils import SOIL_LIBRARY
from agriq.domain.risk.scoring import (
    clamp,
    component_scores,
    risk_color,
    risk_status,
    urgency,
)


def test_all_30_districts_have_coordinates():
    assert len(DISTRICTS) == 30
    for name, (lat, lon) in DISTRICTS.items():
        assert 17 < lat < 24 and 81 < lon < 88


def test_coordinates_fallback_to_cuttack():
    assert coordinates_for("Nowhere") == DISTRICTS["Cuttack"]


def test_profile_for_unknown_district_returns_default():
    profile = profile_for("Unknown District")
    assert "Odisha agro-climatic belt" in profile["zone"]


def test_resolve_crop_known_alias():
    crop, key = resolve_crop("Paddy")
    assert key == "rice"
    assert crop["name"] == "Rice"


def test_resolve_crop_unknown_returns_general_profile():
    crop, key = resolve_crop("Dragon Fruit")
    assert crop["category"] == "General"
    assert crop["name"] == "Dragon Fruit"


def test_crop_display_names_sorted_unique():
    names = crop_display_names()
    assert names == sorted(names)
    assert "Rice" in names


def test_student_domain_config_covers_every_area():
    assert set(STUDENT_DOMAIN_CONFIG) == set(STUDENT_AREAS)
    for area, config in STUDENT_DOMAIN_CONFIG.items():
        assert config["topics"] == STUDENT_AREAS[area]
        assert "show" in config and "pests" in config and "diseases" in config


def test_reference_libraries_present():
    assert "Brown Plant Hopper" in PEST_LIBRARY
    assert "Blast" in DISEASE_LIBRARY
    assert "Alluvial soil" in SOIL_LIBRARY


def test_risk_bands():
    assert risk_status(85) == "CRITICAL"
    assert risk_status(65) == "HIGH"
    assert risk_status(45) == "MODERATE"
    assert risk_status(10) == "LOW"
    assert risk_color(85) == "red"
    assert risk_color(10) == "green"


def test_urgency_messages():
    assert urgency(85) == "Inspect today"
    assert urgency(10) == "Normal monitoring"


def test_clamp():
    assert clamp(150) == 100
    assert clamp(-5) == 0
    assert clamp(42) == 42


def test_component_scores_keys_stable():
    crop, _ = resolve_crop("rice")
    weather = {"temp": 30, "humidity": 80, "rain": 5, "wind": 10}
    comps = component_scores(crop, weather, {"available": False, "evidence_score": 0}, "Cuttack", "Vegetative", "Normal field")
    # Weather-driven components are present when weather is available;
    # zero-value components (district/field/leaf at this input) are omitted.
    assert {"Humidity", "Rainfall", "Temperature", "Crop Sensitivity"}.issubset(set(comps))


def test_component_scores_omit_weather_when_unavailable():
    """Phase 1: unavailable weather never produces generated components."""
    crop, _ = resolve_crop("rice")
    unavailable = {"available": False, "temp": None, "humidity": None, "rain": None}
    comps = component_scores(crop, unavailable, {"available": False, "evidence_score": 0}, "Cuttack", "Vegetative", "Normal field")
    assert "Humidity" not in comps
    assert "Rainfall" not in comps
    assert "Temperature" not in comps
    assert "Crop Sensitivity" in comps  # crop knowledge is still real
