"""Shared Farmer Context service (Phase 1).

Builds ONE structured context for the authenticated farmer — the same
object consumed by the dashboard, the context-aware assistant and the
future Farm Copilot / Risk Intelligence / Market Optimizer modules.

Rules:
- Context is ALWAYS derived from the authenticated user (never a
  browser-supplied id) and ownership is verified at repository level.
- Every external value carries source and freshness.
- Data never crosses farmers: every lookup is scoped to the caller's
  farmer_profile id.
- Missing information is reported as unknown/unavailable — never filled
  with generated values.
"""
from __future__ import annotations

from typing import Any

from ..core.logging import get_logger
from ..core.time import iso_utc
from ..repositories.farmer_repository import (
    CropCycleRepository,
    FieldRepository,
    FarmRepository,
    ObservationRepository,
    ProfileRepository,
    SoilTestRepository,
)
from . import crop_stage_service
from . import weather_service

logger = get_logger("services.farmer_context")


def _unknown() -> dict[str, Any]:
    return {"available": False, "reason": "not_provided", "message": "Not provided by farmer yet."}


def build_farmer_context(
    user_id: int,
    *,
    farm_id: int | None = None,
    field_id: int | None = None,
    crop_cycle_id: int | None = None,
    include_weather: bool = True,
) -> dict[str, Any]:
    """Assemble the full verified context for one authenticated farmer.

    Selection precedence: explicit ids (ownership-verified) → the farmer's
    most recently created farm/field/active cycle → absent sections marked
    unknown.
    """
    context: dict[str, Any] = {"generated_at": iso_utc()}

    profile = ProfileRepository.get_for_user(user_id)
    if profile is None:
        context["farmer"] = None
        context["onboarding_required"] = True
        return context

    context["onboarding_required"] = False
    context["farmer"] = {
        "id": user_id,
        "profile_id": profile.id,
        "full_name": profile.full_name,
        "preferred_language": profile.preferred_language,
        "state": profile.state,
        "district": profile.district,
        "village": profile.village,
    }

    # --- Farm selection (explicit or most recent) --------------------------
    farms = FarmRepository.list_for_profile(profile.id)
    farm = None
    if farm_id is not None:
        farm = FarmRepository.get_owned(farm_id, profile.id)
        if farm is None:
            raise PermissionError("farm_not_owned")
    elif farms:
        farm = farms[0]

    context["farm"] = _farm_dict(farm, farms)

    # --- Field selection ----------------------------------------------------
    field = None
    fields: list = []
    if farm is not None:
        fields = FieldRepository.list_for_farm(farm.id)
        if field_id is not None:
            field = FieldRepository.get_owned(field_id, profile.id)
            if field is None:
                raise PermissionError("field_not_owned")
        elif fields:
            field = fields[0]
    context["field"] = _field_dict(field, fields)

    # --- Soil (source-labelled) ---------------------------------------------
    if field is not None:
        soil_tests = SoilTestRepository.list_for_field(field.id)
        context["soil"] = _soil_dict(soil_tests[0] if soil_tests else None)
    else:
        context["soil"] = _unknown()

    # --- Crop cycle + stage --------------------------------------------------
    cycle = None
    if field is not None:
        if crop_cycle_id is not None:
            cycle = CropCycleRepository.get_owned(crop_cycle_id, profile.id)
            if cycle is None:
                raise PermissionError("crop_cycle_not_owned")
        else:
            cycle = CropCycleRepository.active_cycle_for_field(field.id)
    context["crop_cycle"] = _cycle_dict(cycle)

    # --- Recent observations --------------------------------------------------
    if cycle is not None:
        observations = ObservationRepository.list_for_cycle(cycle.id)[:5]
        context["recent_observations"] = [_observation_summary(o) for o in observations]
    else:
        context["recent_observations"] = []

    # --- Weather (live, with provenance) --------------------------------------
    if include_weather and field is not None:
        context["weather"] = weather_service.get_field_weather(field.id, profile.id)
    else:
        context["weather"] = {
            "available": False,
            "reason": "no_field_selected",
            "message": "Register a field with coordinates to receive weather.",
        }

    # --- Market placeholder (explicit unavailable until requested) ------------
    context["market"] = {
        "available": False,
        "reason": "not_requested",
        "message": "Official matching records unavailable.",
    }
    return context


def _farm_dict(farm, farms: list) -> dict[str, Any] | None:
    if farm is None:
        return None
    field_count = int(farm.fields.count()) if hasattr(farm.fields, "count") else 0
    return {
        "id": farm.id,
        "name": farm.name,
        "state": farm.state,
        "district": farm.district,
        "village": farm.village,
        "latitude": farm.latitude,
        "longitude": farm.longitude,
        "total_area": farm.total_area,
        "area_unit": farm.area_unit,
        "ownership_type": farm.ownership_type,
        "archived": farm.archived_at is not None,
        "field_count": field_count,
    }


def _field_dict(field, fields: list) -> dict[str, Any] | None:
    if field is None:
        return None
    soil_source = None
    latest_soil = SoilTestRepository.list_for_field(field.id)
    if latest_soil:
        soil_source = latest_soil[0].source_type
    cycle_count = int(field.crop_cycles.count()) if hasattr(field.crop_cycles, "count") else 0
    return {
        "id": field.id,
        "farm_id": field.farm_id,
        "name": field.name,
        "area": field.area,
        "area_unit": field.area_unit,
        "soil_type": field.soil_type,
        "irrigation_type": field.irrigation_type,
        "latitude": field.latitude,
        "longitude": field.longitude,
        "soil_source": soil_source,
        "crop_cycle_count": cycle_count,
    }


def _soil_dict(soil) -> dict[str, Any]:
    if soil is None:
        return {
            "available": False,
            "reason": "no_soil_record",
            "message": "No soil record yet. Add a lab report or enter known values; missing values stay unknown.",
        }
    return {
        "available": True,
        "source_type": soil.source_type,
        "tested_at": soil.tested_at.isoformat() if soil.tested_at else None,
        "laboratory_name": soil.laboratory_name,
        "report_reference": soil.report_reference,
        "ph": soil.ph,
        "electrical_conductivity": soil.electrical_conductivity,
        "organic_carbon": soil.organic_carbon,
        "nitrogen": soil.nitrogen,
        "phosphorus": soil.phosphorus,
        "potassium": soil.potassium,
        "document_path": soil.document_path,
        "message": None if soil.source_type == "laboratory_report" else
        "Values shown are from the selected source, not a laboratory report.",
    }


def _cycle_dict(cycle) -> dict[str, Any] | None:
    if cycle is None:
        return None
    stage_calc = None
    if cycle.sowing_date or cycle.transplanting_date:
        stage_calc = crop_stage_service.calculate_stage(
            cycle.crop_name,
            cycle.sowing_date,
            cycle.transplanting_date,
            variety=cycle.variety,
        )
    confirmed = cycle.farmer_confirmed_stage
    return {
        "id": cycle.id,
        "crop": cycle.crop_name,
        "variety": cycle.variety,
        "season": cycle.season,
        "sowing_date": cycle.sowing_date.isoformat() if cycle.sowing_date else None,
        "transplanting_date": cycle.transplanting_date.isoformat() if cycle.transplanting_date else None,
        "expected_harvest_date": cycle.expected_harvest_date.isoformat() if cycle.expected_harvest_date else None,
        "calculated_stage": cycle.calculated_stage or (stage_calc.calculated_stage if stage_calc else None),
        "calculated_stage_reason": stage_calc.reason if stage_calc else None,
        "stage_reference_version": stage_calc.reference_version if stage_calc else None,
        "farmer_confirmed_stage": confirmed,
        "effective_stage": confirmed or (stage_calc.calculated_stage if stage_calc else None),
        "status": cycle.status,
        "previous_crop": cycle.previous_crop,
    }


def _observation_summary(observation) -> dict[str, Any]:
    return {
        "id": observation.id,
        "observed_at": observation.observed_at.isoformat() if observation.observed_at else None,
        "observation_type": observation.observation_type,
        "field_condition": observation.field_condition,
        "notes": observation.notes,
        "farmer_reported_severity": observation.farmer_reported_severity,
        "has_image": bool(observation.image_path),
    }


__all__ = ["build_farmer_context"]
