"""AI assistant API blueprint (POST /ask-ai).

Farmer mode (Phase 1): authenticate → build the shared farmer context →
pass ONLY verified structured context to Gemini → persist the conversation
with per-message provenance → store evidence-backed recommendations when
produced. When Gemini is unavailable the response carries an explicit
unavailable state; a scripted answer is never labelled as AI.

Student/Research mode: unchanged knowledge-engine behaviour, clearly
labelled as the AGRIQ rule-based reference engine.
"""
from __future__ import annotations

import json

from flask import Blueprint, current_app, jsonify, request, session

from ..core.constants import MODE_FARMER
from ..core.logging import get_logger
from ..core.security import current_user, verify_csrf
from ..core.time import iso_utc
from ..repositories.farmer_repository import ConversationRepository, RecommendationRepository
from ..schemas.assistant import parse_assistant_request
from ..services import assistant_orchestrator, farmer_context

logger = get_logger("api.assistant")

assistant_bp = Blueprint("assistant", __name__)


def _sources_block(context: dict, result: dict) -> dict:
    """Provenance stored with every assistant message."""
    weather = context.get("weather") or {}
    market = context.get("market") or {}
    return {
        "farmer_reported": {
            key: context["farmer"].get(key)
            for key in ("full_name", "district", "village")
            if context.get("farmer")
        },
        "verified_provider_data": {
            "weather": {
                "provider": weather.get("provider"),
                "retrieved_at": weather.get("retrieved_at"),
                "live": weather.get("live"),
                "available": weather.get("available"),
            } if weather else None,
            "market": {
                "provider": market.get("provider"),
                "available": market.get("available"),
            } if market else None,
        },
        "agriq_interpretation": "rule-based context assembly",
        "generative_model": result.get("source") if result.get("source") in {"gemini"} else None,
        "unknown_or_unavailable": [
            section for section, payload in
            (("weather", weather), ("market", market))
            if isinstance(payload, dict) and not payload.get("available")
        ],
        "generated_at": iso_utc(),
    }


@assistant_bp.post("/ask-ai")
def ask_ai():
    data = request.get_json(silent=True) or {}
    parsed = parse_assistant_request(data)
    if parsed.is_empty:
        return jsonify({"answer": "Please type a farming or agriculture-study question first."})

    # CSRF applies to the assistant for authenticated browser sessions.
    if session.get("user_contact") is not None:
        token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
        if not verify_csrf(token):
            return jsonify({"answer": "Invalid or missing CSRF token.", "ok": False}), 403

    mode = session.get("user_mode", MODE_FARMER)

    # ---- Student/Research mode: knowledge engine, clearly labelled --------
    if mode != MODE_FARMER:
        result = assistant_orchestrator.ask(parsed.question, mode, parsed.context, current_app.config)
        return jsonify({
            "answer": result["answer"],
            "ok": True,
            "source": result["source"],
            "source_label": result.get("source_label", "AGRIQ knowledge engine"),
        })

    # ---- Farmer mode: shared context + Gemini only -------------------------
    user = current_user()
    if user is None:
        return jsonify({"answer": "Please sign in again to continue.", "ok": False}), 401

    try:
        context = farmer_context.build_farmer_context(user.id)
    except PermissionError:
        return jsonify({"answer": "Farm data could not be verified for this request.", "ok": False}), 403

    # Only verified structured context goes to the model.
    verified_context = _verified_context_for_model(context)
    result = assistant_orchestrator.ask(
        parsed.question, MODE_FARMER, {**verified_context, **parsed.context}, current_app.config
    )

    if result.get("source") == "unavailable":
        return jsonify({
            "answer": result["answer"],
            "ok": False,
            "source": "unavailable",
            "reason": result.get("reason", "gemini_unavailable"),
        })

    # ---- Persistence (farmer mode) ------------------------------------------
    sources = _sources_block(context, result)
    recommendation_payload = None
    try:
        conversation = ConversationRepository.get_or_create(user.id, MODE_FARMER)
        ConversationRepository.add_message(conversation.id, "user", parsed.question)
        ConversationRepository.add_message(
            conversation.id, "assistant", result["answer"], sources=sources
        )
        recommendation_payload = _maybe_store_recommendation(user.id, context, result)
    except Exception as exc:
        logger.warning("assistant_persistence_failed error=%s", type(exc).__name__)

    return jsonify({
        "answer": result["answer"],
        "ok": True,
        "source": result["source"],
        "source_label": "Google Gemini with verified AGRIQ context",
        "sources": sources,
        "recommendation": recommendation_payload,
    })


def _verified_context_for_model(context: dict) -> dict:
    """Flatten the verified context into model-safe key/value facts."""
    facts: dict[str, str] = {}
    farmer = context.get("farmer")
    if farmer:
        if farmer.get("district"):
            facts["district"] = str(farmer["district"])
        if farmer.get("preferred_language"):
            facts["preferred_language"] = str(farmer["preferred_language"])
    farm = context.get("farm")
    if farm:
        facts["farm"] = str(farm.get("name") or "")
    field = context.get("field")
    if field:
        facts["field"] = str(field.get("name") or "")
        if field.get("soil_source"):
            facts["soil_source"] = str(field["soil_source"])
    cycle = context.get("crop_cycle")
    if cycle:
        facts["crop"] = str(cycle.get("crop") or "")
        if cycle.get("variety"):
            facts["variety"] = str(cycle["variety"])
        stage = cycle.get("effective_stage")
        if stage:
            facts["growth_stage"] = str(stage)
            facts["stage_basis"] = (
                "farmer confirmed" if cycle.get("farmer_confirmed_stage") else "calculated reference"
            )
    weather = context.get("weather")
    if isinstance(weather, dict) and weather.get("available"):
        facts["weather_now"] = (
            f"{weather.get('temp')}°C, {weather.get('humidity')}% humidity, "
            f"{weather.get('rain')} mm rain (source: {weather.get('provider')})"
        )
    elif isinstance(weather, dict):
        facts["weather_now"] = "unavailable"
    soil = context.get("soil")
    if isinstance(soil, dict) and soil.get("available"):
        facts["soil_test"] = (
            f"pH {soil.get('ph')}, OC {soil.get('organic_carbon')} "
            f"(source: {soil.get('source_type')})"
        )
    if context.get("recent_observations"):
        latest = context["recent_observations"][0]
        facts["latest_observation"] = str(latest.get("observation_type") or "")
    return facts


def _maybe_store_recommendation(user_id: int, context: dict, result: dict) -> dict | None:
    """Persist an evidence-backed recommendation for actionable answers."""
    answer = result.get("answer") or ""
    if len(answer) < 40:
        return None
    cycle = context.get("crop_cycle") or {}
    field = context.get("field") or {}
    farm = context.get("farm") or {}
    weather = context.get("weather") or {}
    evidence = {
        "weather_available": bool(weather.get("available")),
        "weather_source": weather.get("provider"),
        "soil_source": (context.get("soil") or {}).get("source_type"),
        "crop_cycle_id": cycle.get("id"),
        "generated_at": iso_utc(),
    }
    recommendation = RecommendationRepository.create(user_id, {
        "farm_id": farm.get("id"),
        "field_id": field.get("id"),
        "crop_cycle_id": cycle.get("id"),
        "recommendation_type": "assistant_answer",
        "action": answer[:2000],
        "reasons_json": json.dumps({"question_context": cycle.get("effective_stage")}, ensure_ascii=False),
        "evidence_json": json.dumps(evidence, ensure_ascii=False),
        "confidence": None,
        "requires_expert_confirmation": True,
    })
    return {"id": recommendation.id, "requires_expert_confirmation": True}


__all__ = ["assistant_bp"]
