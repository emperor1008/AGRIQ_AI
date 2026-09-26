"""Farmer-data API blueprint (Phase 1).

All farmer data endpoints in one ownership-checked blueprint:

- Profile:        GET/POST/PATCH /api/profile
- Farms:          GET/POST /api/farms, GET/PATCH /api/farms/{id},
                  POST /api/farms/{id}/archive
- Fields:         GET/POST /api/farms/{id}/fields, GET/PATCH /api/fields/{id},
                  POST /api/fields/{id}/archive
- Soil tests:     GET/POST /api/fields/{id}/soil-tests
- Crop cycles:    GET/POST /api/fields/{id}/crop-cycles,
                  GET/PATCH /api/crop-cycles/{id},
                  POST /api/crop-cycles/{id}/confirm-stage
                  POST /api/crop-cycles/{id}/archive
- Observations:   GET/POST /api/crop-cycles/{id}/observations
- Context:        GET /api/farmer-context
- Market:         GET /api/market-prices

Route bodies handle HTTP concerns only (parse, serialise, status codes);
validation rules live in schemas, business rules in services, data access
in repositories. Ownership is re-verified on every request via the session
user — browser-supplied ids are never trusted.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from ..core.audit import audit_event
from ..core.constants import AWAITING_ANALYSIS_MESSAGE
from ..core.exceptions import NotFoundError, ValidationError
from ..core.logging import get_logger
from ..core.security import current_user, get_csrf_token, require_csrf
from ..repositories.farmer_repository import (
    CropCycleRepository,
    FieldRepository,
    FarmRepository,
    ObservationRepository,
    ProfileRepository,
    SoilTestRepository,
)
from ..schemas.farmer_data import (
    parse_crop_cycle_payload,
    parse_field_payload,
    parse_farm_payload,
    parse_observation_payload,
    parse_profile_payload,
    parse_soil_test_payload,
)
from ..services import crop_stage_service, farmer_context, market_service, uploads

logger = get_logger("api.farmer_data")

farmer_data_bp = Blueprint("farmer_data", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_active_user():
    """Resolve the authenticated, active user or raise."""
    user = current_user()
    if user is None:
        raise NotFoundError("Sign in to continue.")
    if not user.is_active:
        raise NotFoundError("Sign in to continue.")
    return user


def _require_profile(user_id: int):
    profile = ProfileRepository.get_for_user(user_id)
    if profile is None:
        raise ValidationError("Create your farmer profile first.")
    return profile


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _profile_dict(profile) -> dict:
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "full_name": profile.full_name,
        "preferred_language": profile.preferred_language,
        "state": profile.state,
        "district": profile.district,
        "village": profile.village,
        "consent_version": profile.consent_version,
        "consented_at": _iso(profile.consented_at),
    }


def _farm_dict(farm) -> dict:
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
        "archived_at": _iso(farm.archived_at),
        "created_at": _iso(farm.created_at),
    }


def _field_dict(field) -> dict:
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
        "archived": field.archived_at is not None,
        "archived_at": _iso(field.archived_at),
        "created_at": _iso(field.created_at),
    }


def _soil_dict(record) -> dict:
    return {
        "id": record.id,
        "field_id": record.field_id,
        "tested_at": _iso(record.tested_at),
        "laboratory_name": record.laboratory_name,
        "report_reference": record.report_reference,
        "ph": record.ph,
        "electrical_conductivity": record.electrical_conductivity,
        "organic_carbon": record.organic_carbon,
        "nitrogen": record.nitrogen,
        "phosphorus": record.phosphorus,
        "potassium": record.potassium,
        "source_type": record.source_type,
        "has_document": bool(record.document_path),
        "created_at": _iso(record.created_at),
    }


def _cycle_dict(cycle) -> dict:
    stage_calc = None
    if cycle.sowing_date or cycle.transplanting_date:
        stage_calc = crop_stage_service.calculate_stage(
            cycle.crop_name, cycle.sowing_date, cycle.transplanting_date, variety=cycle.variety
        )
    return {
        "id": cycle.id,
        "field_id": cycle.field_id,
        "crop_name": cycle.crop_name,
        "variety": cycle.variety,
        "season": cycle.season,
        "sowing_date": cycle.sowing_date.isoformat() if cycle.sowing_date else None,
        "transplanting_date": cycle.transplanting_date.isoformat() if cycle.transplanting_date else None,
        "expected_harvest_date": cycle.expected_harvest_date.isoformat() if cycle.expected_harvest_date else None,
        "calculated_stage": cycle.calculated_stage or (stage_calc.calculated_stage if stage_calc else None),
        "stage_reason": stage_calc.reason if stage_calc else None,
        "stage_reference_version": stage_calc.reference_version if stage_calc else None,
        "farmer_confirmed_stage": cycle.farmer_confirmed_stage,
        "stage_confirmed_at": _iso(cycle.stage_confirmed_at),
        "effective_stage": cycle.farmer_confirmed_stage
        or (stage_calc.calculated_stage if stage_calc else None),
        "status": cycle.status,
        "previous_crop": cycle.previous_crop,
        "archived": cycle.archived_at is not None,
    }


def _observation_dict(observation) -> dict:
    return {
        "id": observation.id,
        "crop_cycle_id": observation.crop_cycle_id,
        "observed_at": _iso(observation.observed_at),
        "observation_type": observation.observation_type,
        "field_condition": observation.field_condition,
        "notes": observation.notes,
        "latitude": observation.latitude,
        "longitude": observation.longitude,
        "has_image": bool(observation.image_path),
        "farmer_reported_severity": observation.farmer_reported_severity,
        "created_at": _iso(observation.created_at),
    }


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@farmer_data_bp.get("/api/profile")
def get_profile():
    user = _require_active_user()
    profile = ProfileRepository.get_for_user(user.id)
    return jsonify({"ok": True, "profile": _profile_dict(profile) if profile else None})


@farmer_data_bp.post("/api/profile")
@require_csrf
def create_profile():
    user = _require_active_user()
    if ProfileRepository.get_for_user(user.id) is not None:
        raise ValidationError("Farmer profile already exists. Use update instead.")
    data = parse_profile_payload(request.get_json(silent=True) or request.form)
    profile = ProfileRepository.create_for_user(user.id, data)
    audit_event("profile_create", user_id=user.id, profile_id=profile.id, outcome="ok")
    return jsonify({"ok": True, "profile": _profile_dict(profile)}), 201


@farmer_data_bp.patch("/api/profile")
@require_csrf
def update_profile():
    user = _require_active_user()
    profile = _require_profile(user.id)
    data = parse_profile_payload(request.get_json(silent=True) or request.form, partial=True)
    profile = ProfileRepository.update(profile, data)
    audit_event("profile_update", user_id=user.id, profile_id=profile.id, outcome="ok")
    return jsonify({"ok": True, "profile": _profile_dict(profile)})


# ---------------------------------------------------------------------------
# Farms
# ---------------------------------------------------------------------------

@farmer_data_bp.get("/api/farms")
def list_farms():
    user = _require_active_user()
    profile = _require_profile(user.id)
    farms = FarmRepository.list_for_profile(profile.id)
    return jsonify({"ok": True, "farms": [_farm_dict(f) for f in farms]})


@farmer_data_bp.post("/api/farms")
@require_csrf
def create_farm():
    user = _require_active_user()
    profile = _require_profile(user.id)
    data = parse_farm_payload(request.get_json(silent=True) or request.form)
    farm = FarmRepository.create(profile.id, data)
    audit_event("farm_create", user_id=user.id, farm_id=farm.id, outcome="ok")
    return jsonify({"ok": True, "farm": _farm_dict(farm)}), 201


@farmer_data_bp.get("/api/farms/<int:farm_id>")
def get_farm(farm_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    farm = FarmRepository.get_owned(farm_id, profile.id)
    if farm is None:
        raise NotFoundError()
    fields = FieldRepository.list_for_farm(farm.id)
    payload = _farm_dict(farm)
    payload["fields"] = [_field_dict(f) for f in fields]
    return jsonify({"ok": True, "farm": payload})


@farmer_data_bp.patch("/api/farms/<int:farm_id>")
@require_csrf
def update_farm(farm_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    farm = FarmRepository.get_owned(farm_id, profile.id)
    if farm is None:
        raise NotFoundError()
    data = parse_farm_payload(request.get_json(silent=True) or request.form, partial=True)
    farm = FarmRepository.update(farm, data)
    audit_event("farm_update", user_id=user.id, farm_id=farm.id, outcome="ok")
    return jsonify({"ok": True, "farm": _farm_dict(farm)})


@farmer_data_bp.post("/api/farms/<int:farm_id>/archive")
@require_csrf
def archive_farm(farm_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    farm = FarmRepository.get_owned(farm_id, profile.id)
    if farm is None:
        raise NotFoundError()
    farm = FarmRepository.archive(farm)
    audit_event("farm_archive", user_id=user.id, farm_id=farm.id, outcome="ok")
    return jsonify({"ok": True, "farm": _farm_dict(farm)})


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------

@farmer_data_bp.get("/api/farms/<int:farm_id>/fields")
def list_fields(farm_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    farm = FarmRepository.get_owned(farm_id, profile.id)
    if farm is None:
        raise NotFoundError()
    fields = FieldRepository.list_for_farm(farm.id)
    return jsonify({"ok": True, "fields": [_field_dict(f) for f in fields]})


@farmer_data_bp.post("/api/farms/<int:farm_id>/fields")
@require_csrf
def create_field(farm_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    farm = FarmRepository.get_owned(farm_id, profile.id)
    if farm is None:
        raise NotFoundError()
    data = parse_field_payload(request.get_json(silent=True) or request.form)
    field = FieldRepository.create(farm.id, data)
    audit_event("field_create", user_id=user.id, farm_id=farm.id, field_id=field.id, outcome="ok")
    return jsonify({"ok": True, "field": _field_dict(field)}), 201


@farmer_data_bp.get("/api/fields/<int:field_id>")
def get_field(field_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    field = FieldRepository.get_owned(field_id, profile.id)
    if field is None:
        raise NotFoundError()
    payload = _field_dict(field)
    cycles = CropCycleRepository.list_for_field(field.id)
    payload["crop_cycles"] = [_cycle_dict(c) for c in cycles]
    payload["soil_tests"] = [_soil_dict(s) for s in SoilTestRepository.list_for_field(field.id)]
    return jsonify({"ok": True, "field": payload})


@farmer_data_bp.patch("/api/fields/<int:field_id>")
@require_csrf
def update_field(field_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    field = FieldRepository.get_owned(field_id, profile.id)
    if field is None:
        raise NotFoundError()
    data = parse_field_payload(request.get_json(silent=True) or request.form, partial=True)
    field = FieldRepository.update(field, data)
    audit_event("field_update", user_id=user.id, field_id=field.id, outcome="ok")
    return jsonify({"ok": True, "field": _field_dict(field)})


@farmer_data_bp.post("/api/fields/<int:field_id>/archive")
@require_csrf
def archive_field(field_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    field = FieldRepository.get_owned(field_id, profile.id)
    if field is None:
        raise NotFoundError()
    field = FieldRepository.archive(field)
    audit_event("field_archive", user_id=user.id, field_id=field.id, outcome="ok")
    return jsonify({"ok": True, "field": _field_dict(field)})


# ---------------------------------------------------------------------------
# Soil tests
# ---------------------------------------------------------------------------

@farmer_data_bp.get("/api/fields/<int:field_id>/soil-tests")
def list_soil_tests(field_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    field = FieldRepository.get_owned(field_id, profile.id)
    if field is None:
        raise NotFoundError()
    records = SoilTestRepository.list_for_field(field.id)
    return jsonify({"ok": True, "soil_tests": [_soil_dict(r) for r in records]})


@farmer_data_bp.post("/api/fields/<int:field_id>/soil-tests")
@require_csrf
def create_soil_test(field_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    field = FieldRepository.get_owned(field_id, profile.id)
    if field is None:
        raise NotFoundError()
    document_path = None
    upload = request.files.get("report_document")
    if upload is not None and upload.filename:
        document_path = uploads.save_soil_report(user.id, upload)
    payload = request.get_json(silent=True) or request.form
    data = parse_soil_test_payload(payload, document_path=document_path)
    record = SoilTestRepository.create(field.id, data)
    audit_event("soil_test_create", user_id=user.id, field_id=field.id,
                soil_test_id=record.id, source_type=record.source_type, outcome="ok")
    return jsonify({"ok": True, "soil_test": _soil_dict(record)}), 201


# ---------------------------------------------------------------------------
# Crop cycles
# ---------------------------------------------------------------------------

@farmer_data_bp.get("/api/fields/<int:field_id>/crop-cycles")
def list_crop_cycles(field_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    field = FieldRepository.get_owned(field_id, profile.id)
    if field is None:
        raise NotFoundError()
    cycles = CropCycleRepository.list_for_field(field.id)
    return jsonify({"ok": True, "crop_cycles": [_cycle_dict(c) for c in cycles]})


@farmer_data_bp.post("/api/fields/<int:field_id>/crop-cycles")
@require_csrf
def create_crop_cycle(field_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    field = FieldRepository.get_owned(field_id, profile.id)
    if field is None:
        raise NotFoundError()
    data = parse_crop_cycle_payload(request.get_json(silent=True) or request.form)
    cycle = CropCycleRepository.create(field.id, data)
    # Transparent stage calculation on creation (never overwrites farmer input).
    stage = crop_stage_service.calculate_stage(
        cycle.crop_name, cycle.sowing_date, cycle.transplanting_date, variety=cycle.variety
    )
    if stage.calculated_stage:
        cycle.calculated_stage = stage.calculated_stage
        from ..extensions import db

        db.session.commit()
    audit_event("crop_cycle_create", user_id=user.id, field_id=field.id,
                crop_cycle_id=cycle.id, outcome="ok")
    return jsonify({"ok": True, "crop_cycle": _cycle_dict(cycle),
                    "stage_calculation": stage.to_dict()}), 201


@farmer_data_bp.get("/api/crop-cycles/<int:cycle_id>")
def get_crop_cycle(cycle_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    cycle = CropCycleRepository.get_owned(cycle_id, profile.id)
    if cycle is None:
        raise NotFoundError()
    return jsonify({"ok": True, "crop_cycle": _cycle_dict(cycle)})


@farmer_data_bp.patch("/api/crop-cycles/<int:cycle_id>")
@require_csrf
def update_crop_cycle(cycle_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    cycle = CropCycleRepository.get_owned(cycle_id, profile.id)
    if cycle is None:
        raise NotFoundError()
    data = parse_crop_cycle_payload(request.get_json(silent=True) or request.form, partial=True)
    # Farmer confirmation is never silently overwritten by recalculation.
    confirmation = data.pop("farmer_confirmed_stage", None)
    cycle = CropCycleRepository.update(cycle, data)
    if confirmation is not None:
        cycle = CropCycleRepository.update(cycle, {"farmer_confirmed_stage": confirmation})
    return jsonify({"ok": True, "crop_cycle": _cycle_dict(cycle)})


@farmer_data_bp.post("/api/crop-cycles/<int:cycle_id>/confirm-stage")
@require_csrf
def confirm_stage(cycle_id: int):
    """Farmer confirms or corrects the stage; stored separately from the
    calculated value and never overwritten by recalculation."""
    user = _require_active_user()
    profile = _require_profile(user.id)
    cycle = CropCycleRepository.get_owned(cycle_id, profile.id)
    if cycle is None:
        raise NotFoundError()
    payload = request.get_json(silent=True) or request.form
    from ..schemas.farmer_data import parse_stage_confirmation

    stage = parse_stage_confirmation(payload)
    from ..core.time import utc_now

    updated = CropCycleRepository.update(cycle, {
        "farmer_confirmed_stage": stage,
        "stage_confirmed_at": utc_now(),
    })
    audit_event("crop_stage_confirm", user_id=user.id, crop_cycle_id=cycle.id,
                stage=stage, outcome="ok")
    return jsonify({"ok": True, "crop_cycle": _cycle_dict(updated)})


@farmer_data_bp.post("/api/crop-cycles/<int:cycle_id>/archive")
@require_csrf
def archive_crop_cycle(cycle_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    cycle = CropCycleRepository.get_owned(cycle_id, profile.id)
    if cycle is None:
        raise NotFoundError()
    cycle = CropCycleRepository.archive(cycle)
    audit_event("crop_cycle_archive", user_id=user.id, crop_cycle_id=cycle.id, outcome="ok")
    return jsonify({"ok": True, "crop_cycle": _cycle_dict(cycle)})


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------

@farmer_data_bp.get("/api/crop-cycles/<int:cycle_id>/observations")
def list_observations(cycle_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    cycle = CropCycleRepository.get_owned(cycle_id, profile.id)
    if cycle is None:
        raise NotFoundError()
    observations = ObservationRepository.list_for_cycle(cycle.id)
    return jsonify({"ok": True, "observations": [_observation_dict(o) for o in observations]})


@farmer_data_bp.post("/api/crop-cycles/<int:cycle_id>/observations")
@require_csrf
def create_observation(cycle_id: int):
    user = _require_active_user()
    profile = _require_profile(user.id)
    cycle = CropCycleRepository.get_owned(cycle_id, profile.id)
    if cycle is None:
        raise NotFoundError()
    image_path = None
    upload = request.files.get("image")
    if upload is not None and upload.filename:
        image_path = uploads.save_observation_image(user.id, upload)
    data = parse_observation_payload(request.form, image_path=image_path)
    observation = ObservationRepository.create(cycle.id, data)
    audit_event("observation_create", user_id=user.id, crop_cycle_id=cycle.id,
                observation_id=observation.id, observation_type=observation.observation_type,
                outcome="ok")
    return jsonify({"ok": True, "observation": _observation_dict(observation)}), 201


# ---------------------------------------------------------------------------
# Shared context
# ---------------------------------------------------------------------------

@farmer_data_bp.get("/api/farmer-context")
def get_farmer_context():
    user = _require_active_user()
    try:
        context = farmer_context.build_farmer_context(
            user.id,
            farm_id=request.args.get("farm_id", type=int),
            field_id=request.args.get("field_id", type=int),
            crop_cycle_id=request.args.get("crop_cycle_id", type=int),
        )
    except PermissionError:
        raise NotFoundError()
    # Unanalysed map districts are never scored; the UI shows this instead.
    context["map_note"] = AWAITING_ANALYSIS_MESSAGE
    return jsonify({"ok": True, "context": context})


# ---------------------------------------------------------------------------
# Market prices (official records only)
# ---------------------------------------------------------------------------

@farmer_data_bp.get("/api/market-prices")
def get_market_prices():
    user = _require_active_user()
    profile = ProfileRepository.get_for_user(user.id)
    commodity = (request.args.get("commodity") or "").strip()
    district = (request.args.get("district") or (profile.district if profile else "") or "").strip() or None
    if not commodity:
        raise ValidationError("Provide a commodity name.")
    result = market_service.get_mandi_prices(commodity=commodity, district=district)
    return jsonify({"ok": True, "market": result})


@farmer_data_bp.get("/api/csrf-token")
def csrf_token_endpoint():
    """Issue a CSRF token for SPA-style fetches (token stays server-signed)."""
    return jsonify({"ok": True, "csrf_token": get_csrf_token()})


__all__ = ["farmer_data_bp"]
