"""Phase 7 P7-1 — honest-state labelling of the rule-based (non-ML) outputs.

Every test here guards a Phase 7 source-audit finding: a number AGRIQ cannot
source must never be presented as sourced, measured or calibrated.

- F-03  legacy ``confidence`` is a screening band, not a calibrated probability
- F-04  LeafScan confidence is a colour heuristic, not a model probability
- F-05  no rupee figure without the AGMARKNET provider (``MARKET_BASELINE`` gone)
- F-06  the yield-loss band is indicative, not a measurement
- F-07  the composite indices are rule heuristics, not measurements

§4 data policy: every fixture in this module is **TEST_FIXTURE_ONLY**. They exist
so the payload and card builders can be exercised offline; they must never enter
a production database, reach a provider or appear on a farmer screen.
"""
from __future__ import annotations

import json

import pytest

from agriq.core.constants import (
    NO_VERIFIED_IMPACT_MESSAGE,
    TOKEN_DATA_UNAVAILABLE,
    TOKEN_HEURISTIC_NOT_VALIDATED,
    TOKEN_YIELD_IMPACT_NOT_MEASURED,
)
from agriq.domain.risk import scoring
from agriq.domain.risk.recommendations import before_after
from agriq.services import farm_intelligence

# [TEST_FIXTURE_ONLY] Verified-weather shape, mirroring open_meteo's live payload.
WEATHER_FIXTURE = {
    "available": True,
    "live": True,
    "provider": "Open-Meteo",
    "reason": None,
    "provider_observed_at": "2026-09-26T06:00:00+00:00",
    "retrieved_at": "2026-09-26T06:05:00+00:00",
    "temp": 31.0,
    "humidity": 74.0,
    "rain": 0.0,
    "precipitation": 0.0,
    "wind": 6.0,
    "condition": "Partly cloudy",
    "weather_code": 2,
    "hourly": [],
    "daily": [],
    "history": [],
}


def _card(analysis: dict, anchor: str) -> dict:
    cards = farm_intelligence.build_farmer_dropdown_sections(analysis)
    return next(card for card in cards if card["anchor"] == anchor)


def _analysis_fixture() -> dict:
    """[TEST_FIXTURE_ONLY] Offline shape for the farmer dashboard card builder."""
    return {
        "district": "Cuttack",
        "crop": {"name": "Rice", "odia": "ଧାନ"},
        "crop_key": "rice",
        "growth_stage": "Vegetative",
        "field_condition": "Normal field",
        "weather": WEATHER_FIXTURE,
        "weather_available": True,
        "leafscan": {
            "available": True, "preview": None, "symptom": "Mixed early stress signal",
            "confidence": 60, "green_pct": 61.0, "yellow_pct": 12.0,
            "brown_pct": 7.0, "dark_pct": 3.0, "evidence_score": 11,
            "explanation": "colour pattern screening", "recommendation": "confirm in field",
        },
        "components": {"Crop Sensitivity": 12.0, "Humidity": 14.0},
        "risk": 26,
        "status": "LOW",
        "color": "green",
        "urgency": "Normal monitoring",
        "health": scoring.crop_health(26, {"available": True, "evidence_score": 11}),
        "productivity": scoring.productivity_score(26, {"humidity": 74, "rain": 0}, "Vegetative"),
        "yield_loss": scoring.yield_loss_band(26),
        "profit_impact": farm_intelligence.profit_impact(26, "rice"),
        "confidence": scoring.confidence_score(26, {"available": True}, {"available": True}, {"x": 1}),
        "heuristic_status": scoring.heuristic_status(),
        "confidence_status": scoring.confidence_status(),
        "yield_loss_status": scoring.yield_loss_status(),
        "yield_loss_basis": "rule heuristic basis",
        "reasons": {"en": "Fixture reason.", "od": "Fixture reason (od)."},
        "farm_twin": {"district": "Cuttack", "crop": "Rice"},
        "before_after": before_after(26),
        "action_plan": ["Today: continue normal monitoring."],
        "english_advisory": "fixture advisory",
        "odia_advisory": "fixture advisory (od)",
        "market": farm_intelligence.market_advisory("rice", "Cuttack", 26, 70),
        "treatment": {
            "possible_disease": "Blast", "possible_pest": "Stem borer",
            "symptom_basis": "Mixed early stress signal", "decision_rule": "rule",
            "disclaimer_en": "advisory only", "disclaimer_od": "advisory only (od)",
            "prevention": ["scout"], "natural": ["neem"], "chemical": ["label only"],
        },
        "forecast": [],
        "top_hotspots": [],
    }


# ---------------------------------------------------------------------------
# F-05 — no rupee figure without the provider
# ---------------------------------------------------------------------------

def test_market_advisory_is_an_explicit_unavailable_state():
    advisory = farm_intelligence.market_advisory("rice", "Cuttack", 50, 80)

    assert advisory["available"] is False
    assert advisory["status"] == TOKEN_DATA_UNAVAILABLE
    assert advisory["range"] is None
    assert advisory["pressure"] is None
    assert advisory["message"]
    assert "₹" not in json.dumps(advisory)


def test_market_baseline_table_was_removed():
    from agriq.domain.catalogs import crops

    assert not hasattr(crops, "MARKET_BASELINE")
    assert "MARKET_BASELINE" not in crops.__all__


@pytest.mark.parametrize("crop_key", ["rice", "paddy", "tomato", "sugarcane", "dragonfruit"])
def test_profit_impact_never_quotes_rupees(crop_key):
    value = farm_intelligence.profit_impact(60, crop_key)

    assert value == NO_VERIFIED_IMPACT_MESSAGE
    assert "₹" not in value
    assert "per acre" not in value


# ---------------------------------------------------------------------------
# F-03 / F-06 / F-07 — labelled heuristics
# ---------------------------------------------------------------------------

def test_heuristic_outputs_carry_their_status():
    assert scoring.confidence_status() == "CONFIDENCE_NOT_CALIBRATED"
    assert scoring.yield_loss_status() == TOKEN_YIELD_IMPACT_NOT_MEASURED
    assert scoring.heuristic_status() == TOKEN_HEURISTIC_NOT_VALIDATED


def test_screening_band_formulas_are_unchanged():
    """Relabelling must not silently change the published numbers."""
    assert scoring.yield_loss_band(0) == "2% - 10%"
    assert scoring.yield_loss_band(50) == "6% - 17%"
    assert scoring.crop_health(50, {"available": False}) == 71
    assert scoring.productivity_score(50, None, "Vegetative") == 74


def test_before_after_scenario_is_labelled_illustrative():
    scenario = before_after(26)

    assert scenario["status"] == TOKEN_HEURISTIC_NOT_VALIDATED
    assert scenario["basis"]
    assert scenario["untreated"] == scoring.yield_loss_band(26)


def test_analysis_payload_publishes_status_beside_every_heuristic(monkeypatch):
    """``analyze_farm`` must ship status + basis next to its rule numbers."""
    from agriq.integrations.weather import open_meteo

    monkeypatch.setattr(open_meteo, "get_weather", lambda *a, **k: dict(WEATHER_FIXTURE))
    monkeypatch.setattr(open_meteo, "forecast_weather", lambda *a, **k: [])

    analysis = farm_intelligence.analyze_farm("Rice", "Cuttack", "Vegetative", "Normal field", None)

    assert analysis["heuristic_status"] == TOKEN_HEURISTIC_NOT_VALIDATED
    assert analysis["confidence_status"] == "CONFIDENCE_NOT_CALIBRATED"
    assert analysis["yield_loss_status"] == TOKEN_YIELD_IMPACT_NOT_MEASURED
    for key in ("heuristic_basis", "confidence_basis", "yield_loss_basis"):
        assert analysis[key], f"{key} must not be empty"

    # The payload no longer contains any rupee figure at all.
    assert "₹" not in json.dumps(analysis, default=str)
    assert analysis["market"]["available"] is False
    assert analysis["profit_impact"] == NO_VERIFIED_IMPACT_MESSAGE


# ---------------------------------------------------------------------------
# F-06 / F-07 — what the farmer actually reads on the cards
# ---------------------------------------------------------------------------

def test_impact_card_badge_no_longer_states_a_loss_as_fact():
    card = _card(_analysis_fixture(), "yieldHub")

    assert card["badge"] == "Indicative bands — not measured"


def test_impact_card_labels_every_heuristic_row():
    card = _card(_analysis_fixture(), "yieldHub")
    labels = " | ".join(row["left"] for row in card["rows"])

    assert "Crop health (rule estimate, not measured)" in labels
    assert "Yield protection (rule estimate, not measured)" in labels
    assert "If untreated (indicative band, not a measurement)" in labels
    assert "Early-action scenario (illustrative, not a forecast)" in labels


def test_impact_card_rows_contain_no_rupee_figure():
    card = _card(_analysis_fixture(), "yieldHub")

    assert "₹" not in json.dumps(card, default=str)

    mandi = next(row for row in card["rows"] if row["left"] == "Mandi price")
    assert mandi["right"] == "Not available — no verified source"


def test_risk_breakdown_badge_is_labelled_a_rule_estimate():
    card = _card(_analysis_fixture(), "riskBreakdown")

    assert card["badge"] == "26% risk • rule estimate"
