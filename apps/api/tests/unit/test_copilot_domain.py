"""Phase 2 unit tests: intent routing, confidence formula, safety rules,
evidence builder and the weather/unavailable contracts.

All fixtures here are synthetic TEST DATA — they never enter any production
database and are never presented as live information.
"""
from __future__ import annotations

import pytest

from agriq.domain.advisory import intent as intent_mod
from agriq.domain.advisory.recommendation import (
    ConfidenceResult,
    EvidenceItem,
    Recommendation,
    compute_confidence,
)
from agriq.domain.safety.chemical_rules import check_chemical_request
from agriq.domain.safety.escalation import evaluate_escalation
from agriq.integrations.ai import gemini


# ---------------------------------------------------------------------------
# Intent routing (deterministic, multilingual)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("question,expected", [
    ("Should I irrigate my rice field today?", intent_mod.INTENT_IRRIGATION),
    ("Will it rain tomorrow?", intent_mod.INTENT_WEATHER),
    ("मेरे खेत में पानी देना चाहिए?", intent_mod.INTENT_IRRIGATION),
    ("ମୋ ପାଟିରେ ପୋକ ଲାଗିଛି", intent_mod.INTENT_PEST),
    ("Leaves are turning yellow", intent_mod.INTENT_NUTRIENT),
    ("What is the mandi price of paddy?", intent_mod.INTENT_MARKET),
    ("I need an agriculture officer", intent_mod.INTENT_EXPERT_HELP),
])
def test_intent_routes_correctly(question, expected):
    result = intent_mod.route_intent(question)
    assert result.intent == expected
    assert 0.0 <= result.confidence <= 1.0


def test_intent_low_confidence_offers_clarification():
    result = intent_mod.route_intent("zzz qqq")
    assert result.is_low_confidence
    assert result.clarifying_question


def test_intent_is_deterministic():
    question = "Should I irrigate today?"
    first = intent_mod.route_intent(question)
    second = intent_mod.route_intent(question)
    assert first.intent == second.intent
    assert first.confidence == second.confidence


# ---------------------------------------------------------------------------
# Confidence formula (documented, reproducible)
# ---------------------------------------------------------------------------

def test_confidence_high_with_complete_context():
    result = compute_confidence(
        context_completeness=1.0, weather_fresh=True, weather_present=True,
        knowledge_top_score=0.8, knowledge_present=True, direct_observation=True,
        conflicting_evidence=False, missing_critical_inputs=0,
    )
    assert result.level == "high"
    assert result.score >= 0.75


def test_confidence_low_without_evidence():
    result = compute_confidence(
        context_completeness=0.2, weather_fresh=False, weather_present=False,
        knowledge_top_score=0.0, knowledge_present=False, direct_observation=False,
        conflicting_evidence=True, missing_critical_inputs=3,
    )
    assert result.level == "low"
    assert result.score < 0.5


def test_confidence_is_reproducible():
    kwargs = dict(
        context_completeness=0.7, weather_fresh=True, weather_present=True,
        knowledge_top_score=0.5, knowledge_present=True, direct_observation=False,
        conflicting_evidence=False, missing_critical_inputs=1,
    )
    first = compute_confidence(**kwargs)
    second = compute_confidence(**kwargs)
    assert first.score == second.score


def test_confidence_version_is_declared():
    result = compute_confidence(
        context_completeness=0.5, weather_fresh=False, weather_present=False,
        knowledge_top_score=0.0, knowledge_present=False, direct_observation=False,
        conflicting_evidence=False, missing_critical_inputs=0,
    )
    assert result.calculation_version == "copilot-confidence-v1"


# ---------------------------------------------------------------------------
# Safety: chemical rules and escalation
# ---------------------------------------------------------------------------

def test_exact_dosage_blocked_without_approved_evidence():
    result = check_chemical_request("How much urea should I spray per acre?")
    assert result.blocked
    assert result.requires_expert


def test_dosage_blocked_even_with_area_when_no_approved_evidence():
    result = check_chemical_request("How many kg pesticide per acre?", field_area_known=True)
    assert result.blocked
    assert "No approved source" in result.reason


def test_mixing_request_blocked():
    result = check_chemical_request("Can I mix two pesticides and spray?")
    assert result.blocked
    assert result.requires_expert


def test_exposure_emergency_escalates_immediately():
    result = check_chemical_request("My child drank the pesticide, what to do?")
    assert result.escalate_emergency
    assert result.blocked


def test_spray_advice_blocked_without_weather():
    result = check_chemical_request("pest in my field", weather_safe=None)
    assert result.requires_expert
    assert "unavailable" in result.reason.lower()


def test_spray_advice_blocked_in_unsafe_weather():
    result = check_chemical_request("pest in my field", weather_safe=False, weather_fresh=True)
    assert result.blocked


# ---------------------------------------------------------------------------
# Escalation policy
# ---------------------------------------------------------------------------

def test_low_confidence_escalates():
    decision = evaluate_escalation(
        confidence=ConfidenceResult(level="low", score=0.3, basis="test"))
    assert decision.escalate


def test_severe_symptoms_escalate():
    decision = evaluate_escalation(severe_symptoms=True)
    assert decision.escalate
    assert decision.urgency in ("soon", "immediate")
    assert decision.handover_message


def test_emergency_exposure_is_immediate():
    decision = evaluate_escalation(emergency_exposure=True)
    assert decision.escalate
    assert decision.urgency == "immediate"


def test_routine_case_does_not_escalate():
    decision = evaluate_escalation(
        confidence=ConfidenceResult(level="high", score=0.9, basis="ok"))
    assert not decision.escalate


# ---------------------------------------------------------------------------
# Gemini provider contract
# ---------------------------------------------------------------------------

def test_gemini_unconfigured_is_explicit_unavailable():
    result = gemini.generate("hello", api_key="", model="gemini-2.5-flash")
    assert not result.available
    assert result.error_category == "not_configured"


def test_gemini_network_error_is_unavailable(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            raise RuntimeError("boom")

    def fake_post(*args, **kwargs):
        raise ConnectionError("network down")

    monkeypatch.setattr("agriq.integrations.ai.gemini.requests.post", fake_post)
    result = gemini.generate("hello", api_key="test-key", model="m")
    assert not result.available
    assert result.error_category in ("api_error", "invalid_response")


def test_gemini_never_returns_scripted_text_on_failure(monkeypatch):
    def fake_post(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("agriq.integrations.ai.gemini.requests.post", fake_post)
    result = gemini.generate("hello", api_key="test-key", model="m")
    assert result.text is None
    assert not result.available


# ---------------------------------------------------------------------------
# Evidence items always carry provenance
# ---------------------------------------------------------------------------

def test_evidence_item_requires_source_and_time():
    item = EvidenceItem(type="weather_forecast", source="Open-Meteo",
                        observed_or_retrieved_at="2026-09-22T10:00:00+00:00",
                        freshness="live")
    payload = item.to_dict()
    assert payload["source"] == "Open-Meteo"
    assert payload["observed_or_retrieved_at"]
    assert payload["freshness"] == "live"


def test_recommendation_serialisation_includes_evidence():
    rec = Recommendation(
        recommendation_type="irrigation",
        action="Inspect field moisture before irrigating",
        reasons=["Rain is forecast"],
        evidence=[EvidenceItem(type="weather_forecast", source="Open-Meteo",
                               observed_or_retrieved_at="2026-09-22T10:00:00+00:00")],
        confidence=ConfidenceResult(level="medium", score=0.7, basis="ok"),
    )
    data = rec.to_dict()
    assert data["evidence"]
    assert data["confidence"]["level"] == "medium"
    assert data["reasons"]
