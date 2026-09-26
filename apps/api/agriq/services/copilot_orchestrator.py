"""Copilot orchestration engine (Phase 2 §3).

The single pipeline for personalised, evidence-backed farm guidance:

1. Authenticate (route layer guarantees the session user).
2. Verify ownership of field / crop cycle via repositories.
3. Load Shared Farmer Context.
4. Detect intent deterministically.
5. Invoke only the required internal tools (weather/market/knowledge).
6. Retrieve approved knowledge (lexical, threshold-gated).
7. Validate freshness; label stale/unavailable honestly.
8. Apply safety guardrails (chemical rules, escalation policy).
9. Build the structured evidence package.
10. Send only the minimum necessary context to Gemini.
11. Validate the model response.
12. Persist conversation, evidence, provenance run row and recommendation.
13. Return a farmer-friendly response with explicit missing information.

The LLM never decides ownership, data validity or source freshness. Any
Gemini failure maps to the farmer-facing unavailable message — a scripted
answer is never presented as AI output.
"""
from __future__ import annotations

from typing import Any, Optional

from ..core.config import BaseConfig
from ..core.logging import get_logger
from ..domain.advisory import intent as intent_mod
from ..domain.advisory.evidence import (
    crop_cycle_evidence,
    guardrail_evidence,
    knowledge_evidence,
    market_evidence,
    soil_test_evidence,
    weather_evidence,
)
from ..domain.advisory.recommendation import (
    ConfidenceResult,
    EvidenceItem,
    Recommendation,
    compute_confidence,
)
from ..domain.safety.chemical_rules import check_chemical_request
from ..domain.safety.escalation import evaluate_escalation
from ..integrations.ai import gemini
from ..integrations.knowledge.retriever import KnowledgeRetriever
from ..repositories.copilot_repository import AssistantRunRepository, ConversationRepository
from . import conversation_service
from . import recommendation_service
from .crop_cycle_advisor import build_stage_recommendation
from .farmer_context import build_farmer_context
from .weather_advisor import build_weather_recommendation

logger = get_logger("services.copilot")

PROMPT_TEMPLATE_VERSION = "copilot-prompt-v1"
AI_UNAVAILABLE_MESSAGE = "The AI assistant is temporarily unavailable."
CLARIFICATION_SENTINEL = "__clarification__"


def run_copilot(
    *,
    user_id: int,
    profile_id: int,
    question: str,
    language: str = "en",
    field_id: Optional[int] = None,
    crop_cycle_id: Optional[int] = None,
    conversation_ref: Optional[str] = None,
    response_mode: str = "full",
    config: BaseConfig,
) -> dict[str, Any]:
    """Execute one copilot turn end-to-end and return the API payload."""
    question = (question or "").strip()
    if not question:
        return {"ok": False, "error": "empty_question",
                "answer": "Please type your question."}

    # -- 1/2. Ownership-scoped context (raises PermissionError on foreign ids) --
    try:
        context = build_farmer_context(
            user_id,
            field_id=field_id,
            crop_cycle_id=crop_cycle_id,
            include_weather=False,
        )
    except PermissionError:
        return {"ok": False, "error": "not_found",
                "answer": "That field or crop cycle could not be found for your account."}
    if context is None:
        return {"ok": False, "error": "context_unavailable",
                "answer": "Please complete your farmer profile and register a farm first."}

    field = context.get("field") or {}
    cycle = context.get("crop_cycle") or {}

    # -- 3/4. Conversation + memory ------------------------------------------
    conversation, created = conversation_service.get_or_create_conversation(
        user_id, conversation_service_mode(), conversation_ref,
    )
    memory = conversation_service.conversation_memory(conversation.id)

    # -- 5. Intent ------------------------------------------------------------
    intent = intent_mod.route_intent(question)

    # -- 6. Tools (only what the intent needs) --------------------------------
    weather = None
    market = None
    market_intel: dict[str, Any] = {}
    if "weather" in intent.requires_tools:
        weather = _get_weather(context, field.get("id"), profile_id)
        context["weather"] = weather
    if intent.intent == intent_mod.INTENT_CROP_CHOICE:
        market_intel = _market_intelligence(user_id, context, question,
                                            capabilities=["crop_options"])
    elif "market" in intent.requires_tools:
        market_intel = _market_intelligence(user_id, context, question)

    # -- 7. Knowledge retrieval (approved-only, threshold-gated) --------------
    retriever = KnowledgeRetriever()
    retrieval = retriever.retrieve(
        question,
        crop=cycle.get("crop"),
        stage=cycle.get("farmer_confirmed_stage") or cycle.get("calculated_stage"),
        district=(context.get("farmer") or {}).get("district"),
        state=(context.get("farmer") or {}).get("state"),
        language=language,
    )

    # -- 8. Safety guardrails (pre-LLM) ----------------------------------------
    # The spray-weather gate only applies when the question is actually about
    # spraying/chemicals; a rain mention in an irrigation question must not
    # trip it (issue found in live verification).
    _spray_words = ("spray", "pesticide", "insecticide", "fungicide", "herbicide",
                    "chemical", "weedicid", "dose", "dosage")
    question_is_spray_related = any(w in question.lower() for w in _spray_words)
    field_area_known = field.get("area") is not None
    weather_fresh = bool(weather and weather.get("available") and (weather.get("live") or weather.get("cached")) and not weather.get("stale"))
    weather_safe = None
    if weather is not None and weather.get("available"):
        wind_kmh = float(weather.get("wind") or 0)
        rain_active = bool(weather.get("rain")) or float(weather.get("precipitation") or 0) > 0
        weather_safe = bool(wind_kmh < 15.0 and not rain_active)
    chemical = check_chemical_request(
        question,
        approved_dosage_evidence=False,  # Phase 2: no dosage evidence ingested yet
        field_area_known=field_area_known,
        weather_safe=weather_safe if question_is_spray_related else None,
        weather_fresh=weather_fresh,
    )
    emergency = chemical.escalate_emergency

    # -- 9. Evidence package ---------------------------------------------------
    evidence_items = []
    weather_item = weather_evidence(weather)
    if weather_item:
        evidence_items.append(weather_item.to_dict())
    if cycle:
        evidence_items.append(crop_cycle_evidence({
            "id": cycle.get("id"), "crop": cycle.get("crop"),
            "stage": cycle.get("farmer_confirmed_stage") or cycle.get("calculated_stage"),
            "sowing_date": cycle.get("sowing_date"), "updated_at": cycle.get("updated_at"),
        }).to_dict())
    soil = context.get("soil") or {}
    soil_available = bool(soil.get("available"))
    if soil_available:
        soil_item = soil_test_evidence(soil)
        if soil_item:
            evidence_items.append(soil_item.to_dict())
    if retrieval.available:
        for passage in retrieval.passages:
            evidence_items.append(knowledge_evidence(passage.to_dict()).to_dict())
    guardrail_item = guardrail_evidence(chemical)
    if guardrail_item:
        evidence_items.append(guardrail_item.to_dict())
    for item in _market_intel_evidence(market_intel):
        evidence_items.append(item.to_dict())

    # -- 10. Structured recommendation from verified context -------------------
    recommendation: Recommendation
    if intent.intent == intent_mod.INTENT_MARKET:
        recommendation = _market_intel_recommendation(market_intel)
        if recommendation is None:
            # Phase 6 had nothing usable (for example no crop registered yet):
            # fall back to the official-record path exactly as before.
            market = _get_market(context)
            recommendation = _market_recommendation(context, market)
    elif intent.intent == intent_mod.INTENT_CROP_CHOICE:
        recommendation = _crop_choice_recommendation(market_intel)
    elif "weather" in intent.requires_tools and intent.intent != intent_mod.INTENT_IRRIGATION:
        recommendation = build_weather_recommendation(context, weather, intent_type=intent.intent)
    else:
        recommendation = build_stage_recommendation(
            context, weather, retrieval,
            intent_type=intent.intent,
            focus_action="Inspect field moisture before irrigating" if intent.intent == intent_mod.INTENT_IRRIGATION else None,
        )
    if chemical.blocked and not emergency:
        recommendation.reasons.append(chemical.reason or "Blocked by safety guardrails.")
        recommendation.requires_expert_confirmation = True

    # -- 11. Confidence --------------------------------------------------------
    confidence = recommendation.confidence or compute_confidence(
        context_completeness=0.5, weather_fresh=weather_fresh,
        weather_present=bool(weather and weather.get("available")),
        knowledge_top_score=retrieval.top_score if retrieval.available else 0.0,
        knowledge_present=retrieval.available,
        direct_observation=bool(context.get("recent_observations")),
        conflicting_evidence=False,
        missing_critical_inputs=len(recommendation.missing_information),
    )

    # -- 12. Escalation policy --------------------------------------------------
    severity_flags = _symptom_severity(question)
    escalation = evaluate_escalation(
        confidence=confidence,
        severe_symptoms=severity_flags["severe"],
        symptoms_spreading=severity_flags["spreading"],
        condition_unsupported=not retrieval.available and intent.intent in (
            intent_mod.INTENT_PEST, intent_mod.INTENT_DISEASE, intent_mod.INTENT_NUTRIENT,
        ),
        conflicting_evidence=False,
        exact_chemical_requested=chemical.blocked and not emergency,
        emergency_exposure=emergency,
        crop_loss_substantial=severity_flags["loss"],
    )

    # -- 13. Provenance run row -------------------------------------------------
    run = AssistantRunRepository.start(
        conversation.id, provider="gemini",
        model=str(config.get("GEMINI_MODEL", "gemini-2.5-flash")),
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
    )

    # -- 14. Gemini call (minimum necessary context) ----------------------------
    answer_text: Optional[str] = None
    provider_status = "completed"
    error_category: Optional[str] = None
    if escalation.escalate and escalation.urgency == "immediate":
        # Short-circuit: emergency handover never needs a model call.
        answer_text = escalation.handover_message
        provider_status = "skipped_emergency"
    else:
        prompt = build_copilot_prompt(
            question=question, context=context,            intent=intent,
            retrieval=retrieval, recommendation=recommendation,
            memory=memory, language=language, escalation=escalation,
            chemical=chemical, response_mode=response_mode,
            market_intelligence=market_intel,
        )
        provider_result = gemini.generate(
            prompt,
            api_key=config.get("GEMINI_API_KEY", ""),
            model=str(config.get("GEMINI_MODEL", "gemini-2.5-flash")),
            timeout_seconds=int(config.get("GEMINI_TIMEOUT_SECONDS", 30)),
        )
        if provider_result.available and provider_result.text:
            answer_text = provider_result.text
        else:
            provider_status = "unavailable"
            error_category = provider_result.error_category

    # -- 15. Gemini failure → explicit unavailable state ------------------------
    if answer_text is None:
        if provider_status == "unavailable":
            answer_text = AI_UNAVAILABLE_MESSAGE
            provider_status = "unavailable"
        elif escalation.escalate:
            answer_text = escalation.handover_message or AI_UNAVAILABLE_MESSAGE

    # -- 16. Persistence ----------------------------------------------------------
    context_record_ids = [r for r in (
        (context.get("farmer") or {}).get("id"),
        (context.get("farm") or {}).get("id"),
        (field or {}).get("id"),
        (cycle or {}).get("id"),
    ) if r]
    retrieved_source_ids = [p.source_id for p in retrieval.passages] if retrieval.available else []

    user_message_id, assistant_message_id = conversation_service.record_turn(
        conversation.id, question, answer_text or AI_UNAVAILABLE_MESSAGE,
        sources={
            "evidence": evidence_items,
            "intent": intent.intent,
            "retrieval_method": retrieval.method,
            "retrieval_available": retrieval.available,
            "retrieval_reason": retrieval.reason,
            "confidence": confidence.to_dict(),
            "missing_information": recommendation.missing_information,
            "escalation": escalation.to_dict(),
            "requires_expert_confirmation": recommendation.requires_expert_confirmation or escalation.escalate,
        },
    )
    assistant_message = ConversationRepository.get_message(assistant_message_id)
    AssistantRunRepository.complete(
        run.id,
        message_id=assistant_message_id,
        context_record_ids=context_record_ids,
        retrieved_source_ids=retrieved_source_ids,
        status=provider_status,
        error_category=error_category,
    )

    # -- 17. Structured recommendation persistence (when actionable) -------------
    recommendation_id: Optional[int] = None
    if recommendation.action and confidence.level != "low" and not chemical.blocked:
        recommendation_id = recommendation_service.persist_recommendation(
            user_id, recommendation.to_dict(),
            farm_id=(context.get("farm") or {}).get("id"),
            field_id=(field or {}).get("id"),
            crop_cycle_id=(cycle or {}).get("id"),
        )

    # -- 18. Response --------------------------------------------------------------
    payload: dict[str, Any] = {
        "ok": True,
        "conversation_id": getattr(conversation, "uuid", None) or str(conversation.id),
        "message_id": (getattr(assistant_message, "uuid", None) if assistant_message else None)
        or str(assistant_message_id),
        "answer": answer_text or AI_UNAVAILABLE_MESSAGE,
        "recommended_actions": [recommendation.action] if recommendation.action else [],
        "reasons": recommendation.reasons,
        "evidence": evidence_items,
        "confidence": confidence.to_dict(),
        "missing_information": recommendation.missing_information,
        "requires_expert_confirmation": bool(recommendation.requires_expert_confirmation or escalation.escalate),
        "escalation": escalation.to_dict() if escalation.escalate else None,
        "valid_until": recommendation.valid_until,
        "language": language,
        "intent": intent.intent,
        "retrieval": {
            "available": retrieval.available,
            "method": retrieval.method,
            "reason": retrieval.reason,
        },
        "sources": [
            {
                "source_id": p.source_id,
                "title": p.title,
                "organisation": p.organisation,
                "section": p.section_reference,
                "publication_date": p.publication_date,
                "relevance": round(p.relevance, 3),
                "retrieved_at": p.retrieved_at,
            }
            for p in retrieval.passages
        ] if retrieval.available else [],
        "context_summary": {
            "crop": cycle.get("crop"),
            "stage": cycle.get("farmer_confirmed_stage") or cycle.get("calculated_stage"),
            "field": field.get("name"),
            "weather_freshness": (weather or {}).get("freshness"),
            "soil_available": bool((context.get("soil") or {}).get("available")),
        },
        "recommendation_id": recommendation_id,
        "assistant_message_id": assistant_message_id,
    }
    if market_intel:
        payload["market_intelligence"] = _trim_market_intel(market_intel)
    if response_mode == "compact":
        return _compact_payload(payload)
    return payload


def _compact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Low-bandwidth response: one action, few reasons, freshness, one warning."""
    warning = None
    if payload.get("requires_expert_confirmation"):
        warning = "Expert confirmation is advised for this guidance."
    elif payload.get("missing_information"):
        warning = f"Missing: {payload['missing_information'][0]}"
    return {
        "ok": payload.get("ok", False),
        "conversation_id": payload.get("conversation_id"),
        "answer": payload.get("answer"),
        "action": (payload.get("recommended_actions") or [None])[0],
        "reasons": (payload.get("reasons") or [])[:3],
        "data_freshness": payload.get("context_summary", {}).get("weather_freshness"),
        "warning": warning,
        "follow_up": "Record what you did and what you saw in your field timeline.",
        "recommendation_id": payload.get("recommendation_id"),
    }


def conversation_service_mode() -> str:
    """Copilot conversations always run in farmer mode."""
    return "farmer"


def _get_weather(context: dict[str, Any], field_id: Optional[int], profile_id: int):
    from .weather_service import get_field_weather
    if not field_id:
        return None
    try:
        return get_field_weather(field_id, profile_id)
    except Exception as exc:  # noqa: BLE001 — provider failure must not crash the turn
        logger.warning("weather_tool_failed error=%s", type(exc).__name__)
        return {"available": False, "reason": "Live weather is currently unavailable."}


def _get_market(context: dict[str, Any]):
    from .market_service import get_mandi_prices
    farmer = context.get("farmer") or {}
    commodity = (context.get("crop_cycle") or {}).get("crop")
    if not commodity:
        return {"available": False, "reason": "Official market records need a registered crop."}
    try:
        return get_mandi_prices(
            commodity=commodity,
            district=farmer.get("district"),
            state=farmer.get("state") or "Odisha",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("market_tool_failed error=%s", type(exc).__name__)
        return {"available": False, "reason": "Official market records are currently unavailable."}


#: Cues deciding which Phase 6 capability a market question actually needs. A
#: question about the price needs one capability, not the whole engine.
_MARKET_TIMING_CUES = ("sell", "wait", "hold", "store", "keep")
_MARKET_FORECAST_CUES = ("forecast", "next week", "next month", "expected price",
                         "future", "predict", "price after")
_MARKET_COST_CUES = ("transport", "distance", "travel", "logistics", "cost",
                     "net value", "profit", "freight", "gross")
_MARKET_COMPARISON_CUES = ("which mandi", "where should i sell", "best price",
                           "which market", "best mandi", "compare")

#: Verbose blocks dropped from the chat payload; the full payloads live at
#: ``/api/v1/market/*``.
_MARKET_PAYLOAD_DROPPED_KEYS = ("series", "quarantined_records")


def _market_capabilities(question: str) -> list[str]:
    """Which Phase 6 capabilities this question needs."""
    lowered = (question or "").lower()
    wanted: list[str] = []
    if any(cue in lowered for cue in _MARKET_TIMING_CUES):
        wanted.append("timing")
    if any(cue in lowered for cue in _MARKET_FORECAST_CUES):
        wanted.append("forecast")
    if any(cue in lowered for cue in _MARKET_COST_CUES + _MARKET_COMPARISON_CUES):
        wanted.append("overview")
    return wanted or ["overview"]


def _market_intelligence(
    user_id: int,
    context: dict[str, Any],
    question: str,
    *,
    capabilities: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Structured Phase 6 results for this turn.

    The model explains these values; it never computes them. Every capability is
    called inside its own guard so one degradation cannot break the turn, and a
    failure becomes an explicit ``unavailable`` entry.
    """
    from . import market_intelligence as market_intel

    cycle = context.get("crop_cycle") or {}
    field_id = (context.get("field") or {}).get("id")
    cycle_id = cycle.get("id")
    crop = cycle.get("crop")
    wanted = capabilities or _market_capabilities(question)

    bundle: dict[str, Any] = {"capabilities": wanted, "crop": crop}
    for capability in wanted:
        try:
            if capability == "timing":
                bundle["sell_hold"] = market_intel.sell_hold(
                    user_id, field_id=field_id, crop_cycle_id=cycle_id, commodity=crop,
                )
            elif capability == "forecast":
                bundle["forecast"] = market_intel.forecast_prices(
                    user_id, field_id=field_id, crop_cycle_id=cycle_id, commodity=crop,
                )
            elif capability == "crop_options":
                bundle["crop_options"] = market_intel.crop_options(
                    user_id, field_id=field_id, crop_cycle_id=cycle_id,
                    crops=[crop] if crop else None,
                )
            else:
                bundle["overview"] = market_intel.overview(
                    user_id, field_id=field_id, crop_cycle_id=cycle_id, commodity=crop,
                )
        except Exception as exc:  # noqa: BLE001 - degradation must not break a turn
            logger.warning(
                "market_intelligence_failed capability=%s error=%s", capability, type(exc).__name__
            )
            bundle[capability] = {"ok": False, "status": "unavailable"}
    return bundle


def _trim_market_intel(value: Any) -> Any:
    """Drop verbose series/row dumps from the chat payload."""
    if isinstance(value, dict):
        return {key: _trim_market_intel(item) for key, item in value.items()
                if key not in _MARKET_PAYLOAD_DROPPED_KEYS}
    if isinstance(value, list):
        return [_trim_market_intel(item) for item in value]
    return value


def _market_intel_evidence(bundle: dict[str, Any], limit: int = 3) -> list[EvidenceItem]:
    """Evidence items for the structured market facts used this turn."""
    if not bundle:
        return []
    items: list[EvidenceItem] = []
    overview = bundle.get("overview") or {}
    provenance = overview.get("provenance") or {}
    for row in (overview.get("latest_prices") or [])[:limit]:
        items.append(EvidenceItem(
            type="market_record",
            source=str(row.get("source") or "AGMARKNET via data.gov.in"),
            observed_or_retrieved_at=row.get("retrieved_at") or row.get("price_date"),
            detail=(
                f"{bundle.get('crop')} modal price {row.get('modal_price')} ₹/quintal at "
                f"{row.get('market')} on {row.get('price_date')}"
            ),
            freshness=str(provenance.get("freshness_status") or "unavailable"),
        ))
    forecast = bundle.get("forecast") or {}
    outcome = forecast.get("forecast") or {}
    if outcome.get("status") == "ok" and outcome.get("forecast"):
        first = outcome["forecast"][0]
        interval = outcome.get("prediction_interval") or {}
        items.append(EvidenceItem(
            type="market_forecast",
            source=f"AGRIQ {outcome.get('model_version')} ({outcome.get('selected_model')})",
            observed_or_retrieved_at=(forecast.get("provenance") or {}).get("observed_at"),
            detail=(
                f"Forecast {first.get('modal_price')} ₹/quintal for {first.get('date')} "
                f"(interval {interval.get('lower')}-{interval.get('upper')}, "
                f"out-of-sample dispersion {interval.get('dispersion')})"
            ),
            freshness=str((forecast.get("provenance") or {}).get("freshness_status") or "unavailable"),
        ))
    timing = bundle.get("sell_hold") or {}
    if timing.get("decision"):
        items.append(EvidenceItem(
            type="market_decision",
            source="AGRIQ sell/hold decision support",
            observed_or_retrieved_at=(timing.get("provenance") or {}).get("observed_at"),
            detail=f"Timing view {timing['decision']} from {len(timing.get('evidence') or [])} evidence point(s).",
            freshness=str((timing.get("provenance") or {}).get("freshness_status") or "unavailable"),
        ))
    options = bundle.get("crop_options") or {}
    for option in (options.get("options") or [])[:limit]:
        items.append(EvidenceItem(
            type="crop_suitability",
            source="AGRIQ crop catalog + district agro-climatic profile",
            detail=(
                f"{option.get('crop_name')}: {option.get('recommendation_status')} "
                f"(rank {option.get('rank')})"
            ),
            freshness="n/a",
        ))
    return items


def _market_intel_recommendation(bundle: dict[str, Any]) -> Optional[Recommendation]:
    """Sell/hold → forecast → price recommendation, or None when unusable."""
    if not bundle:
        return None

    timing = bundle.get("sell_hold") or {}
    if timing.get("ok") and timing.get("decision"):
        decision = str(timing["decision"])
        if decision == "INSUFFICIENT_DATA":
            return Recommendation(
                recommendation_type="market_timing",
                action=(timing.get("reason") or "Not enough verified market evidence to advise timing"),
                reasons=[
                    "Timing advice needs a verified price plus an observed trend, forecast, "
                    "storage fact or crop risk — the missing items are listed.",
                ] + list(timing.get("missing_information") or [])[:3],
                evidence=_market_intel_evidence(bundle),
                confidence=ConfidenceResult(
                    level="low", score=0.2,
                    basis="Evidence is insufficient to support a timing view.",
                ),
                missing_information=list(timing.get("missing_information") or []),
            )
        observations = [entry["observation"] for entry in (timing.get("evidence") or [])
                        if entry.get("kind") != "price"][:3]
        return Recommendation(
            recommendation_type="market_timing",
            action=f"Timing view: {decision.replace('_', ' ')}.",
            reasons=observations or ["Based on the latest official record."],
            evidence=_market_intel_evidence(bundle),
            confidence=ConfidenceResult(
                level="medium", score=0.6,
                basis=(
                    "Transparent rule assessment over official records; not calibrated, "
                    "so no probability is claimed."
                ),
            ),
            requires_expert_confirmation=bool(timing.get("requires_expert_confirmation")),
            missing_information=list(timing.get("missing_information") or []),
        )

    forecast = (bundle.get("forecast") or {}).get("forecast") or {}
    if forecast.get("status") == "ok" and forecast.get("forecast"):
        first = forecast["forecast"][0]
        interval = forecast.get("prediction_interval") or {}
        return Recommendation(
            recommendation_type="market_forecast",
            action=(
                f"Official records project {first.get('modal_price')} ₹/quintal for "
                f"{first.get('date')}."
            ),
            reasons=[
                f"Model {forecast.get('selected_model')} ({forecast.get('model_version')}), trained "
                f"on {forecast.get('observations')} official observation date(s).",
                f"Range {interval.get('lower')}-{interval.get('upper')} ₹/quintal from out-of-sample "
                "error; not a calibrated interval.",
            ],
            evidence=_market_intel_evidence(bundle),
            confidence=ConfidenceResult(
                level="medium", score=0.55,
                basis="Chronological backtest against baselines; probabilities are not calibrated.",
            ),
            missing_information=[],
        )

    overview = bundle.get("overview") or {}
    prices = overview.get("latest_prices") or []
    if overview.get("ok") and prices:
        best = prices[0]
        return Recommendation(
            recommendation_type="market_price",
            action=(
                f"Latest official modal price for {bundle.get('crop')} is "
                f"{best.get('modal_price')} ₹/quintal at {best.get('market')} "
                f"({best.get('price_date')})."
            ),
            reasons=[
                f"{(overview.get('provenance') or {}).get('detail') or 'Official records only.'}",
                "AGMARKNET publishes provisional daily prices, not live quotes.",
            ],
            evidence=_market_intel_evidence(bundle),
            confidence=ConfidenceResult(
                level="high", score=0.85,
                basis="Direct official record; no estimation involved.",
            ),
            missing_information=list(overview.get("limitations") or [])[:1],
        )
    return None


def _crop_choice_recommendation(bundle: dict[str, Any]) -> Recommendation:
    """Crop-choice advice from the suitability and stored-price engines."""
    payload = bundle.get("crop_options") or {}
    options = payload.get("options") or []
    if not payload.get("ok") or not options:
        return Recommendation(
            recommendation_type="crop_choice",
            action=(
                payload.get("message")
                or "AGRIQ cannot judge crop choice without your district and a registered crop cycle."
            ),
            reasons=["Crop choice needs the farm district and season from your profile."],
            evidence=_market_intel_evidence(bundle),
            confidence=ConfidenceResult(
                level="low", score=0.2,
                basis="Required context for crop choice is missing.",
            ),
            missing_information=["district", "season"],
        )
    top = options[0]
    market = top.get("market") or {}
    reasons = list(top.get("reasons") or [])[:3]
    if market.get("price_context_available"):
        reasons.append(
            f"Stored official records for this crop: mean latest modal price "
            f"{market.get('latest_modal_price')} ₹/quintal from {market.get('markets_reporting')} market(s)."
        )
    else:
        reasons.append(
            "No official price record is stored for this crop in your district yet, so no price "
            "comparison is offered."
        )
    if top.get("limitation"):
        reasons.append(str(top["limitation"]))
    return Recommendation(
        recommendation_type="crop_choice",
        action=(
            f"{top.get('crop_name')} is the best-supported option for {payload.get('district')} "
            f"this season ({top.get('recommendation_status')})."
        ),
        reasons=reasons,
        evidence=_market_intel_evidence(bundle),
        confidence=ConfidenceResult(
            level="low", score=0.3,
            basis=(
                "Rule-based agronomic suitability over curated catalogs; not calibrated, so no "
                "probability is claimed."
            ),
        ),
        requires_expert_confirmation=bool(top.get("requires_expert_confirmation")),
        missing_information=list(top.get("missing_information") or []),
    )


def _market_recommendation(context: dict[str, Any], market: Optional[dict[str, Any]]) -> Recommendation:
    """Market-price intent: only official records, never estimates."""
    from ..domain.advisory.recommendation import ConfidenceResult
    records = (market or {}).get("records") or []
    if records:
        first = records[0]
        return Recommendation(
            recommendation_type="market_price",
            action=f"Official modal price for {first.get('commodity')} at {first.get('market')} is {first.get('modal_price')} (arrival {first.get('arrival_date')}).",
            reasons=[f"Source: {first.get('source')}", "Only records returned by the official source are shown."],
            evidence=[market_evidence(first).to_dict()],
            confidence=ConfidenceResult(level="high", score=0.9,
                                        basis="Direct official record; no estimation involved."),
        )
    return Recommendation(
        recommendation_type="market_price",
        action="No official market record is available for your crop and district right now.",
        reasons=["Official matching records unavailable."],
        evidence=[],
        confidence=ConfidenceResult(level="low", score=0.2,
                                    basis="No official record returned by the provider."),
    )


_SYMPTOM_WORDS = {
    "severe": ("severe", "heavy damage", "dying", "dead", "large area", "whole field", "extensive"),
    "spread": ("spreading", "spreading fast", "spreading rapidly", "more plants", "increasing"),
    "loss": ("total loss", "crop loss", "failed", "destroyed", "ruined"),
}


def _symptom_severity(question: str) -> dict[str, bool]:
    lowered = (question or "").lower()
    return {
        "severe": any(w in lowered for w in _SYMPTOM_WORDS["severe"]),
        "spreading": any(w in lowered for w in _SYMPTOM_WORDS["spread"]),
        "loss": any(w in lowered for w in _SYMPTOM_WORDS["loss"]),
    }


def build_copilot_prompt(
    *,
    question: str,
    context: dict[str, Any],
    intent: intent_mod.IntentResult,
    retrieval,
    recommendation: Recommendation,
    memory: list[dict[str, str]],
    language: str,
    escalation,
    chemical,
    response_mode: str,
    market_intelligence: Optional[dict[str, Any]] = None,
) -> str:
    """Build the copilot prompt: verified context in, grounded answer out.

    Only relevant, ownership-verified records are included; size is bounded.
    The prompt states the evidence and forbids invented citations.
    """
    cycle = context.get("crop_cycle") or {}
    field = context.get("field") or {}
    weather = context.get("weather") or {}
    soil = context.get("soil") or {}
    soil_summary = soil.get("summary") if soil.get("available") else None

    language_names = {"en": "English", "hi": "Hindi", "or": "Odia"}
    lang_name = language_names.get(language, "English")

    lines: list[str] = [
        "You are AGRIQ AI Farm Copilot, an agriculture assistant for Indian farmers.",
        f"Answer in {lang_name}. Use simple sentences a farmer can act on.",
        "RULES:",
        "- Use ONLY the verified context below; never invent weather, prices, soil values, diagnoses or citations.",
        "- If information is missing, say what is missing instead of guessing.",
        "- Do not give exact pesticide or fertiliser quantities; refer to approved local advisories.",
        "- Distinguish: farmer-reported facts, provider data, AGRIQ rule-based interpretation, your explanation, and unknown information.",
        "",
        f"FARMER QUESTION: {question}",
        f"DETECTED INTENT: {intent.intent}",
        "",
        "VERIFIED FARMER CONTEXT:",
        f"- Crop: {cycle.get('crop') or 'not recorded'}",
        f"- Variety: {cycle.get('variety') or 'not recorded'}",
        f"- Stage: {cycle.get('farmer_confirmed_stage') or cycle.get('calculated_stage') or 'not confirmed'}",
        f"- Sowing date: {cycle.get('sowing_date') or 'not recorded'}",
        f"- Field: {field.get('name') or 'not recorded'} (irrigation: {field.get('irrigation_type') or 'not recorded'})",
        f"- Soil: {soil_summary or 'No verified soil-test value has been recorded.'}",
    ]
    if weather.get("available"):
        lines.append(
            f"- Weather (Open-Meteo, {weather.get('freshness')}): "
            f"{weather.get('temp')}°C, humidity {weather.get('humidity')}%, "
            f"precipitation {weather.get('precipitation')} mm, wind {weather.get('wind')} km/h"
        )
    else:
        lines.append("- Weather: Live weather is currently unavailable.")

    if retrieval.available:
        lines.append("")
        lines.append("APPROVED KNOWLEDGE EXCERPTS (cite only these):")
        for passage in retrieval.passages:
            lines.append(
                f"- [{passage.source_key}] {passage.title} — {passage.organisation} "
                f"(section: {passage.section_reference}): {passage.content[:400]}"
            )
    else:
        lines.append("")
        lines.append("APPROVED KNOWLEDGE: none met the relevance threshold — say verified guidance is unavailable for specifics.")

    if memory:
        lines.append("")
        lines.append("RECENT CONVERSATION (this conversation only):")
        for turn in memory[-4:]:
            lines.append(f"- {turn['role']}: {turn['content'][:200]}")

    if market_intelligence:
        lines.append("")
        lines.append("STRUCTURED MARKET INTELLIGENCE (use these values exactly; never recalculate):")
        summary = _trim_market_intel(market_intelligence)
        overview = summary.get("overview") or {}
        for row in (overview.get("latest_prices") or [])[:3]:
            lines.append(
                f"- Official record: {row.get('commodity') or summary.get('crop')} "
                f"{row.get('modal_price')} ₹/quintal at {row.get('market')} on {row.get('price_date')} "
                f"({row.get('source')})"
            )
        trend = overview.get("trend") or {}
        if trend.get("status") == "ok":
            lines.append(
                f"- Trend: {trend.get('direction')} {trend.get('change_percent')}% over "
                f"{trend.get('points')} official observation date(s)"
            )
        elif overview:
            lines.append(f"- Trend unavailable: {trend.get('reason')}")
        timing = summary.get("sell_hold") or {}
        if timing.get("decision"):
            lines.append(f"- Timing view: {timing.get('decision')} ({timing.get('decision_basis')})")
        forecast = (summary.get("forecast") or {}).get("forecast") or {}
        if forecast.get("status") == "ok" and forecast.get("forecast"):
            first = forecast["forecast"][0]
            lines.append(
                f"- Forecast ({forecast.get('selected_model')}): {first.get('modal_price')} "
                f"₹/quintal for {first.get('date')}"
            )
        elif forecast.get("status"):
            lines.append(f"- Forecast withheld: {forecast.get('reason')}")
        options = summary.get("crop_options") or {}
        for option in (options.get("options") or [])[:4]:
            lines.append(
                f"- Crop option: {option.get('crop_name')} — {option.get('recommendation_status')}"
            )
        provider = overview.get("provider") or (summary.get("forecast") or {}).get("provider")
        if provider:
            lines.append(f"- Provider state: {provider}")

    lines.extend([
        "",
        "STRUCTURED RECOMMENDATION (ground your answer in this):",
        f"- Action: {recommendation.action}",
    ])
    for reason in recommendation.reasons[:5]:
        lines.append(f"- Reason: {reason}")
    if recommendation.missing_information:
        lines.append(f"- Missing information: {', '.join(recommendation.missing_information)}")
    if escalation.escalate:
        lines.append(f"- EXPERT ESCALATION ACTIVE ({escalation.urgency}): include the handover message: {escalation.handover_message}")
    if chemical.blocked:
        lines.append(f"- SAFETY BLOCK: {chemical.reason}")

    if response_mode == "compact":
        lines.append(
            "FORMAT: compact mode — one recommended action, up to three reasons, "
            "data freshness, one warning/limitation, one follow-up step. Keep it short."
        )
    else:
        lines.append(
            "FORMAT: a short farmer-friendly answer, the one clear action, why, "
            "and what is still unknown. Keep under 250 words."
        )
    return "\n".join(lines)


__all__ = ["run_copilot", "build_copilot_prompt", "PROMPT_TEMPLATE_VERSION", "AI_UNAVAILABLE_MESSAGE"]
