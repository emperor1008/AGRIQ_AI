"""Crop-stage calculation tests (Phase 1).

The calculator is transparent and reference-based; it must never silently
overwrite farmer confirmation and must report honestly when the reference
is unavailable.
"""
from __future__ import annotations

from datetime import date, timedelta

from agriq.services.crop_stage_service import calculate_stage, needs_farmer_stage_selection


def test_rice_vegetative_window():
    sowing = date.today() - timedelta(days=35)
    result = calculate_stage("Rice", sowing)
    assert result.calculated_stage == "Vegetative"
    assert result.reference_version
    assert result.farmer_confirmation_required is True
    assert result.days_elapsed == 35
    assert "window" in result.reason


def test_transplanting_date_wins_as_anchor():
    sowing = date.today() - timedelta(days=60)
    transplanting = date.today() - timedelta(days=10)
    result = calculate_stage("Rice", sowing, transplanting)
    assert result.calculated_stage == "Seedling"  # 10 days from transplanting
    assert "transplanting" in result.reason


def test_flowering_window():
    sowing = date.today() - timedelta(days=60)
    result = calculate_stage("rice", sowing)
    assert result.calculated_stage == "Flowering"


def test_beyond_reference_suggests_harvest():
    sowing = date.today() - timedelta(days=200)
    result = calculate_stage("Rice", sowing)
    assert result.calculated_stage == "Harvest Stage"
    assert "beyond" in result.reason


def test_future_date_is_rejected_honestly():
    sowing = date.today() + timedelta(days=10)
    result = calculate_stage("Rice", sowing)
    assert result.calculated_stage is None
    assert "future" in result.reason


def test_missing_date_asks_farmer_to_select():
    result = calculate_stage("Rice", None)
    assert result.calculated_stage is None
    assert result.farmer_confirmation_required is True
    assert "select" in result.reason.lower()


def test_perennial_crop_reference_unavailable():
    """Perennial crops ask the farmer — the calendar cannot claim a stage."""
    result = calculate_stage("Mango", date.today() - timedelta(days=30))
    assert result.calculated_stage is None
    assert result.reference_version is None
    assert "not available" in result.reason
    assert needs_farmer_stage_selection("Mango") is True


def test_unknown_crop_reference_unavailable():
    result = calculate_stage("Dragon Fruit", date.today() - timedelta(days=30))
    assert result.calculated_stage is None
    assert needs_farmer_stage_selection("Dragon Fruit") is True


def test_result_serialises_to_dict():
    result = calculate_stage("Rice", date.today() - timedelta(days=30))
    payload = result.to_dict()
    assert set(payload) == {
        "calculated_stage", "reason", "reference_version",
        "farmer_confirmation_required", "days_elapsed",
    }
