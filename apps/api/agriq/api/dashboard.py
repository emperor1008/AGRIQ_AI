"""Dashboard blueprint (GET/POST /dashboard) — HTTP concerns only.

All analysis work is delegated to ``services.farm_intelligence`` and
``services.student_intelligence``; this module only parses the request,
calls services and renders the template.
"""
from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, session, url_for

from ..core.constants import MODE_FARMER, SESSION_USER_KEY
from ..core.logging import get_logger
from ..core.security import get_csrf_token, is_authenticated
from ..core.time import now_ist
from ..domain.catalogs.crops import (
    FIELD_CONDITIONS,
    GROWTH_STAGES,
    crop_display_names,
    resolve_crop,
)
from ..domain.catalogs.districts import DISTRICTS
from ..domain.catalogs.education import (
    ACADEMIC_LEVELS,
    ANIMAL_LIBRARY,
    FARMING_METHODS,
    FIELD_PROBLEM_OPTIONS,
    OUTPUT_FORMATS,
    PLANT_CATEGORIES,
    STUDENT_AREAS,
    STUDENT_DOMAIN_CONFIG,
    STUDY_DEPTHS,
    STUDY_PURPOSES,
)
from ..domain.catalogs.soils import SOIL_LIBRARY
from ..core.security import current_user
from ..schemas.farmer import parse_farm_request
from ..services import farm_intelligence, student_intelligence
from ..services import farmer_context as farmer_context_service

logger = get_logger("api.dashboard")

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    if not is_authenticated():
        return redirect(url_for("auth.index"))

    user_mode = session.get("user_mode", MODE_FARMER)
    analysis = None
    student = None
    selected_district = None
    selected_crop = None
    selected_stage = "Vegetative"
    selected_condition = "Normal field"
    context = None

    # Phase 1: shared farmer context for the My Farm Data section.
    if user_mode == MODE_FARMER:
        user = current_user()
        if user is not None:
            try:
                context = farmer_context_service.build_farmer_context(
                    user.id, include_weather=False
                )
                if context.get("crop_cycle") and context["crop_cycle"].get("id"):
                    # Stamp the active cycle id for the stage-confirm form.
                    context["crop_cycle"]["active_id"] = context["crop_cycle"]["id"]
            except Exception:
                logger.warning("farmer_context_unavailable", exc_info=True)
                context = None

    crop_for_map, _ = resolve_crop("rice")
    map_data = farm_intelligence.make_map_data(crop_for_map, growth_stage=selected_stage, field_condition=selected_condition)

    if request.method == "POST":
        if user_mode == MODE_FARMER:
            farm_request = parse_farm_request(request.form)
            selected_crop = farm_request.crop
            selected_district = farm_request.district
            selected_stage = farm_request.growth_stage
            selected_condition = farm_request.field_condition
            analysis = farm_intelligence.analyze_farm(
                farm_request.crop,
                farm_request.district,
                farm_request.growth_stage,
                farm_request.field_condition,
                request.files.get("leaf_photo"),
            )
            map_data = analysis["map_data"]
        else:
            student = student_intelligence.student_result(request.form)
            selected_crop = request.form.get("crop", "Rice")

    return render_template(
        "dashboard/index.html",
        page="dashboard",
        user_mode=user_mode,
        user_contact=session.get(SESSION_USER_KEY),
        time=now_ist().strftime("%d %b %Y • %I:%M %p"),
        districts=DISTRICTS,
        crop_names=crop_display_names(),
        student_areas=STUDENT_AREAS,
        student_domain_config=STUDENT_DOMAIN_CONFIG,
        academic_levels=ACADEMIC_LEVELS,
        study_purposes=STUDY_PURPOSES,
        study_depths=STUDY_DEPTHS,
        output_formats=OUTPUT_FORMATS,
        plant_categories=PLANT_CATEGORIES,
        soil_types=list(SOIL_LIBRARY.keys()),
        farming_methods=list(FARMING_METHODS.keys()),
        field_problem_options=FIELD_PROBLEM_OPTIONS,
        animal_species_options=list(ANIMAL_LIBRARY.keys()),
        growth_stages=GROWTH_STAGES,
        field_conditions=FIELD_CONDITIONS,
        analysis=analysis,
        student=student,
        context=context,
        map_data=map_data,
        selected_district=selected_district,
        selected_crop=selected_crop,
        selected_stage=selected_stage,
        selected_condition=selected_condition,
        csrf_token=get_csrf_token(),
        engine_mode="Farm Intelligence" if user_mode == MODE_FARMER else "Student Research Intelligence",
    )
