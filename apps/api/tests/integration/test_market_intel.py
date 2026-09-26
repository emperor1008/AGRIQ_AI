"""Phase 6 integration tests — Farm-to-Market API and service.

Exercises the real chain (session auth → profile → farm → field → crop cycle →
farmer context → stored official records → engines → API contract) plus the
failure paths: no provider key, a provider that raises, thin history, missing
crop cycle, foreign ids, invalid input and secret exposure.

The price rows seeded here are explicitly TEST FIXTURES shaped like documented
AGMARKNET fields; they exist only inside the in-memory test database and are
never shipped as data.
"""
from __future__ import annotations

import re
import sys
from datetime import timedelta
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from agriq.core.time import utc_now  # noqa: E402
from agriq.extensions import db  # noqa: E402
from agriq.models.farmer import MarketPriceRecord  # noqa: E402

TEST_CONTEXT_HEADERS = {"X-CSRF-Token": "test-csrf-token"}

MARKET_GET_ROUTES = (
    "/api/v1/market/overview",
    "/api/v1/market/forecast",
    "/api/v1/market/demand",
    "/api/v1/market/evidence",
)
MARKET_POST_ROUTES = (
    "/api/v1/market/crop-options",
    "/api/v1/market/sell-hold",
    "/api/v1/market/logistics",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def market_farmer(auth_client):
    """Farmer with profile, farm, field and an active rice crop cycle."""
    client = auth_client
    client.post("/api/profile", json={
        "full_name": "Market Farmer", "state": "Odisha", "district": "Cuttack",
        "preferred_language": "en",
    }, headers=TEST_CONTEXT_HEADERS)
    farm = client.post("/api/farms", json={
        "name": "Market Farm", "district": "Cuttack", "latitude": 20.46, "longitude": 85.88,
    }, headers=TEST_CONTEXT_HEADERS).get_json()["farm"]
    field = client.post(f"/api/farms/{farm['id']}/fields", json={
        "name": "Paddy Block", "area": 2.0, "area_unit": "acre",
        "irrigation_type": "canal", "latitude": 20.46, "longitude": 85.88,
    }, headers=TEST_CONTEXT_HEADERS).get_json()["field"]
    cycle = client.post(f"/api/fields/{field['id']}/crop-cycles", json={
        "crop_name": "Rice", "variety": "Swarna", "season": "Kharif",
        "sowing_date": "2026-07-10",
    }, headers=TEST_CONTEXT_HEADERS).get_json()["crop_cycle"]
    return {"client": client, "farm": farm, "field": field, "cycle": cycle}


def seed_price_history(days: int, *, district: str = "Cuttack", commodity: str = "Rice",
                       start_price: float = 2000.0, step: float = 5.0, market: str = "Cuttack Mandi"):
    """Insert TEST FIXTURE rows shaped exactly like stored AGMARKNET records."""
    today = utc_now().date()
    for index in range(days):
        day = today - timedelta(days=days - 1 - index)
        modal = start_price + step * index + (((index * 37) % 11) - 5) * 6
        db.session.add(MarketPriceRecord(
            source="AGMARKNET via data.gov.in",
            state="Odisha", district=district, market=market, commodity=commodity,
            variety="Common", arrival_date=day,
            minimum_price=round(modal - 20, 2), maximum_price=round(modal + 20, 2),
            modal_price=round(modal, 2), retrieved_at=utc_now(), raw_record_hash=f"fixture-{index}",
        ))
    db.session.commit()


# ---------------------------------------------------------------------------
# Authentication, ownership, CSRF
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("route", MARKET_GET_ROUTES)
def test_market_views_require_authentication(client, route):
    assert client.get(route).status_code == 404


@pytest.mark.parametrize("route", MARKET_POST_ROUTES)
def test_market_actions_require_authentication(client, route):
    assert client.post(route, json={}).status_code == 404


@pytest.mark.parametrize("route", MARKET_POST_ROUTES)
def test_market_actions_require_csrf(market_farmer, route):
    response = market_farmer["client"].post(route, json={})
    assert response.status_code == 400


def test_foreign_field_is_404_not_403(market_farmer, second_farmer_client):
    second_farmer_client.post("/api/profile", json={
        "full_name": "Other Market Farmer", "state": "Odisha", "district": "Jajpur",
    }, headers=TEST_CONTEXT_HEADERS)
    farm = second_farmer_client.post("/api/farms", json={"name": "Other Farm"},
                                     headers=TEST_CONTEXT_HEADERS).get_json()["farm"]
    field = second_farmer_client.post(f"/api/farms/{farm['id']}/fields", json={"name": "Other Field"},
                                      headers=TEST_CONTEXT_HEADERS).get_json()["field"]

    response = market_farmer["client"].get(
        f"/api/v1/market/overview?field_id={field['id']}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Honest insufficiency
# ---------------------------------------------------------------------------

def test_overview_without_a_crop_cycle_is_explicit(client, auth_client):
    auth_client.post("/api/profile", json={
        "full_name": "No Cycle Farmer", "state": "Odisha", "district": "Cuttack",
    }, headers=TEST_CONTEXT_HEADERS)
    payload = auth_client.get("/api/v1/market/overview").get_json()
    assert payload["ok"] is False
    assert payload["status"] == "insufficient_data"
    assert "crop" in payload["message"].lower()


def test_overview_without_records_shows_no_numbers(market_farmer):
    payload = market_farmer["client"].get("/api/v1/market/overview").get_json()
    assert payload["ok"] is True
    assert payload["latest_prices"] == []
    assert payload["trend"]["status"] == "insufficient_data"
    assert payload["provenance"]["freshness_status"] == "unavailable"
    # No provider key configured in tests: the provider state is explicit.
    assert payload["provider"]["available"] is False
    assert payload["provider"]["reason"] == "api_key_not_configured"
    assert any("no usable official records" in note.lower() for note in payload["limitations"])


def test_demand_capability_reports_why_it_is_unavailable(market_farmer):
    payload = market_farmer["client"].get("/api/v1/market/demand").get_json()
    assert payload["demand"]["available"] is False
    assert payload["demand"]["reason"] == "arrivals_not_published_by_configured_source"
    assert payload["demand"]["classification"] is None


def test_forecast_refuses_with_a_documented_reason(market_farmer):
    payload = market_farmer["client"].get("/api/v1/market/forecast").get_json()
    outcome = payload["forecast"]
    assert outcome["status"] == "insufficient_data"
    assert outcome["forecast"] == []
    assert outcome["prediction_interval"] is None
    assert str(payload["observations"]) in outcome["reason"]
    assert payload["limitations"]


def test_sell_hold_without_evidence_is_insufficient_data(market_farmer):
    payload = market_farmer["client"].post(
        "/api/v1/market/sell-hold", json={}, headers=TEST_CONTEXT_HEADERS).get_json()
    assert payload["ok"] is True
    assert payload["decision"] == "INSUFFICIENT_DATA"
    assert payload["missing_information"]


def test_logistics_with_a_quantity_but_no_rate_keeps_the_net_incomplete(market_farmer):
    seed_price_history(4)
    payload = market_farmer["client"].post(
        "/api/v1/market/logistics", json={"quantity_quintals": 10},
        headers=TEST_CONTEXT_HEADERS).get_json()
    rows = payload["comparison"]["groups"][0]["markets"]
    assert rows
    for row in rows:
        assert row["economics"]["gross_value"] == round(row["modal_price"] * 10, 2)
        assert row["economics"]["label"] == "NET_VALUE_INCOMPLETE"
        assert row["economics"]["estimated_net_value"] is None


def test_farmer_supplied_costs_complete_the_net_value(market_farmer):
    """Blank stays unknown; a supplied figure — including a real 0 — completes it."""
    seed_price_history(4)
    client = market_farmer["client"]

    # A lump-sum freight figure is a value the farmer knows, so it works even
    # where the in-district distance proxy carries no information (§26).
    complete = client.post("/api/v1/market/logistics", json={
        "quantity_quintals": 10, "transport_cost_total": 1200,
        "input_cost_total": 4000, "market_fee_total": 0,
    }, headers=TEST_CONTEXT_HEADERS).get_json()
    row = complete["comparison"]["groups"][0]["markets"][0]
    assert row["estimated_transport_cost"] == 1200.0
    assert row["economics"]["missing_costs"] == []
    assert row["economics"]["label"] == "estimated_net_value"
    assert row["economics"]["estimated_net_value"] == round(row["modal_price"] * 10, 2) - 5200
    assert row["economics"]["known_costs"]["market_fee_total"] == 0

    # Nothing is defaulted for the farmer: one blank component withholds the net.
    partial = client.post("/api/v1/market/logistics", json={
        "quantity_quintals": 10, "transport_cost_total": 1200, "input_cost_total": 4000,
    }, headers=TEST_CONTEXT_HEADERS).get_json()
    economics = partial["comparison"]["groups"][0]["markets"][0]["economics"]
    assert economics["label"] == "NET_VALUE_INCOMPLETE"
    assert economics["missing_costs"] == ["market_fee_total"]


def test_negative_cost_components_are_rejected(market_farmer):
    client = market_farmer["client"]
    for field in ("transport_rate_per_km_quintal", "transport_cost_total",
                  "input_cost_total", "market_fee_total"):
        response = client.post("/api/v1/market/logistics", json={"quantity_quintals": 5, field: -1},
                               headers=TEST_CONTEXT_HEADERS)
        assert response.status_code == 400, field
    assert client.get("/api/v1/market/overview?transport_rate_per_km_quintal=0").status_code == 200
    assert client.get("/api/v1/market/overview?transport_cost_total=0").status_code == 200
    assert client.get("/api/v1/market/overview?transport_cost_total=-5").status_code == 400


def test_market_panel_asks_for_sale_details_without_prefilling_them(market_farmer):
    """The cost check is fed only by the farmer — no input ships with a value."""
    html = market_farmer["client"].get("/dashboard").get_data(as_text=True)
    assert 'id="farmToMarket"' in html
    assert 'id="marketLogistics"' in html
    for field_id in ("marketQuantity", "marketTransportRate", "marketFreight",
                     "marketInputCost", "marketMarketFee"):
        match = re.search(r'<input[^>]*id="' + field_id + r'"[^>]*>', html)
        assert match, f"{field_id} is missing from the panel"
        assert "value=" not in match.group(0), f"{field_id} must not be prefilled"
    # Storage is a three-state answer: unstated is not the same as "no storage".
    assert "Not stated" in html


# ---------------------------------------------------------------------------
# Real stored history → real outputs
# ---------------------------------------------------------------------------

def test_overview_reports_records_trend_and_provenance(market_farmer):
    seed_price_history(10)
    payload = market_farmer["client"].get("/api/v1/market/overview").get_json()

    assert payload["ok"] is True
    assert payload["price_unit"] == "INR_per_quintal"
    assert payload["provider_commodity"] == "Rice"
    assert payload["latest_prices"], "stored official rows must surface"
    assert all(row["modal_price"] for row in payload["latest_prices"])
    assert payload["trend"]["status"] == "ok"
    assert payload["trend"]["direction"] == "rising"
    assert payload["provenance"]["freshness_status"] in ("fresh", "aging")
    assert payload["provenance"]["is_live"] is False
    assert payload["data_quality"]["accepted"] >= 10


def test_forecast_is_published_only_from_real_history(market_farmer):
    client = market_farmer["client"]
    # Thin history → refusal, and the refusal states the location scope it used.
    seed_price_history(5)
    thin = client.get("/api/v1/market/forecast").get_json()
    assert thin["forecast"]["status"] == "insufficient_data"
    assert any("Cuttack" in note for note in thin["limitations"])

    # Another district's plentiful history must NOT be substituted for this one.
    seed_price_history(40, market="Puri Mandi", district="Puri", start_price=2050.0)
    still_thin = client.get("/api/v1/market/forecast").get_json()
    assert still_thin["forecast"]["status"] == "insufficient_data"
    assert still_thin["observations"] == thin["observations"]

    # Enough history in the farmer's own district → a forecast with chronological
    # evaluation metadata.
    seed_price_history(40, market="Choudwar Mandi", district="Cuttack", start_price=2050.0)
    rich = client.get("/api/v1/market/forecast").get_json()
    outcome = rich["forecast"]
    assert outcome["status"] == "ok"
    assert outcome["training_period"]["to"] < outcome["evaluation_period"]["from"]
    assert len(outcome["forecast"]) == 7
    assert outcome["metrics"]["reported_block"]["candidates"]
    assert outcome["prediction_interval"]["dispersion"] > 0


def test_forecast_horizon_validation(market_farmer):
    response = market_farmer["client"].get("/api/v1/market/forecast?horizon_days=5")
    assert response.status_code == 400


def test_crop_options_rank_district_crops_and_never_invent_prices(market_farmer):
    payload = market_farmer["client"].post(
        "/api/v1/market/crop-options", json={}, headers=TEST_CONTEXT_HEADERS).get_json()
    assert payload["ok"] is True
    assert payload["district"] == "Cuttack"
    options = payload["options"]
    assert options and options[0]["rank"] == 1
    assert options[0]["crop"] == "rice", "the district's documented main crop leads"
    statuses = [option["recommendation_status"] for option in options]
    assert all(status in ("suitable", "marginal", "unsuitable", "insufficient_data")
               for status in statuses)
    # No stored records were seeded: price context must be explicitly absent.
    assert all(option["market"]["price_context_available"] is False for option in options)
    assert payload["confidence"]["status"] == "not_calibrated"


def test_crop_options_use_stored_price_context_when_it_exists(market_farmer):
    seed_price_history(4)
    payload = market_farmer["client"].post(
        "/api/v1/market/crop-options", json={"crops": ["rice"]},
        headers=TEST_CONTEXT_HEADERS).get_json()
    option = payload["options"][0]
    assert option["market"]["price_context_available"] is True
    assert option["market"]["latest_modal_price"] is not None
    assert option["market"]["price_unit"] == "INR_per_quintal"


def test_crop_options_reject_oversized_or_malformed_requests(market_farmer):
    too_many = market_farmer["client"].post(
        "/api/v1/market/crop-options", json={"crops": [f"crop-{i}" for i in range(20)]},
        headers=TEST_CONTEXT_HEADERS)
    assert too_many.status_code == 400
    malformed = market_farmer["client"].post(
        "/api/v1/market/crop-options", json={"crops": "rice"},
        headers=TEST_CONTEXT_HEADERS)
    assert malformed.status_code == 400


def test_sell_hold_uses_stored_history_and_reports_evidence(market_farmer):
    seed_price_history(10)
    payload = market_farmer["client"].post(
        "/api/v1/market/sell-hold", json={"storage_available": True},
        headers=TEST_CONTEXT_HEADERS).get_json()
    assert payload["decision"] in ("SELL_NOW", "WAIT", "MONITOR", "INSUFFICIENT_DATA")
    assert payload["current_price"] is not None
    assert payload["confidence"]["status"] == "not_calibrated"
    assert payload["evidence"], "the decision must show its evidence points"
    assert payload["provenance"]["source"] == "AGMARKNET via data.gov.in"


def test_evidence_report_documents_sources_without_secrets(market_farmer):
    response = market_farmer["client"].get("/api/v1/market/evidence")
    body = response.get_data(as_text=True)
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["sources"][0]["name"].startswith("AGMARKNET")
    assert payload["sources"][0]["resource_id"]
    assert payload["freshness_policy"]["classifier"].startswith("domain.risk_engine.freshness")
    assert "api-key" not in body.lower()
    assert "DATA_GOV_IN_API_KEY" not in body


# ---------------------------------------------------------------------------
# Validation and degradation
# ---------------------------------------------------------------------------

def test_quantity_and_rate_validation(market_farmer):
    client = market_farmer["client"]
    assert client.post("/api/v1/market/logistics", json={"quantity_quintals": 0},
                       headers=TEST_CONTEXT_HEADERS).status_code == 400
    assert client.post("/api/v1/market/logistics", json={"quantity_quintals": "many"},
                       headers=TEST_CONTEXT_HEADERS).status_code == 400
    assert client.post("/api/v1/market/logistics",
                       json={"quantity_quintals": 1_000_001},
                       headers=TEST_CONTEXT_HEADERS).status_code == 400
    assert client.get("/api/v1/market/overview?quantity_quintals=-4").status_code == 400
    assert client.get("/api/v1/market/forecast?field_id=abc").status_code == 400


def test_storage_flag_validation(market_farmer):
    response = market_farmer["client"].post(
        "/api/v1/market/sell-hold", json={"storage_available": "maybe"},
        headers=TEST_CONTEXT_HEADERS)
    assert response.status_code == 400


def test_provider_outage_degrades_to_stored_history(market_farmer, monkeypatch):
    seed_price_history(6)
    from agriq.services import market_service

    def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(market_service, "get_mandi_prices", boom)
    payload = market_farmer["client"].get("/api/v1/market/overview").get_json()

    assert payload["ok"] is True, "stored history must still be served"
    assert payload["provider"]["available"] is False
    assert payload["provider"]["reason"] == "provider_request_failed"
    assert payload["latest_prices"], "verified stored records are still shown"
    assert all(row["source"] == "AGMARKNET via data.gov.in" for row in payload["latest_prices"])


def test_unresolvable_commodity_argument_returns_no_estimated_data(market_farmer):
    payload = market_farmer["client"].get(
        "/api/v1/market/overview?commodity=Unobtainium").get_json()
    assert payload["ok"] is True
    assert payload["latest_prices"] == []
    assert payload["trend"]["status"] == "insufficient_data"


def test_paddy_and_rice_records_are_not_blended(market_farmer):
    seed_price_history(3, commodity="Rice", start_price=3000.0)
    seed_price_history(3, commodity="Paddy(Dhan)(Common)", start_price=2000.0,
                       market="Paddy Mandi")
    payload = market_farmer["client"].get("/api/v1/market/overview").get_json()
    prices = [row["modal_price"] for row in payload["latest_prices"]]
    assert prices, "one provider commodity must still be served"
    assert all(price < 2500 for price in prices) or all(price > 2500 for price in prices)


# ---------------------------------------------------------------------------
# Copilot integration (§15)
# ---------------------------------------------------------------------------

def test_copilot_prefers_structured_market_intelligence(market_farmer, monkeypatch):
    seed_price_history(10)
    from agriq.integrations.ai import gemini
    from agriq.services import copilot_orchestrator

    captured: dict = {}

    def fake_build(**kwargs):
        captured.update(kwargs)
        return "prompt"

    class FakeResult:
        available = True
        text = "Answer."
        error_category = None

    monkeypatch.setattr(copilot_orchestrator, "build_copilot_prompt", fake_build)
    monkeypatch.setattr(gemini, "generate", lambda *args, **kwargs: FakeResult())

    payload = copilot_orchestrator.run_copilot(
        user_id=1, profile_id=1, question="Should I sell now or wait?",
        field_id=market_farmer["field"]["id"], crop_cycle_id=market_farmer["cycle"]["id"],
        config=copilot_orchestrator.BaseConfig(),
    )

    assert payload["ok"] is True
    assert payload["intent"] == "market_price"
    assert "market_intelligence" in payload
    assert payload["market_intelligence"]["capabilities"] == ["timing"]
    assert payload["market_intelligence"]["sell_hold"]["decision"] in (
        "SELL_NOW", "WAIT", "MONITOR", "INSUFFICIENT_DATA")
    # The model receives the structured values, not a blank prompt.
    assert captured.get("market_intelligence")
    assert any(item["type"] in ("market_record", "market_decision")
               for item in payload["evidence"])


def test_copilot_crop_choice_question_routes_to_suitability(market_farmer, monkeypatch):
    from agriq.integrations.ai import gemini
    from agriq.services import copilot_orchestrator

    class FakeResult:
        available = True
        text = "Answer."
        error_category = None

    monkeypatch.setattr(gemini, "generate", lambda *args, **kwargs: FakeResult())

    payload = copilot_orchestrator.run_copilot(
        user_id=1, profile_id=1, question="Which crop should I grow this season?",
        field_id=market_farmer["field"]["id"], crop_cycle_id=market_farmer["cycle"]["id"],
        config=copilot_orchestrator.BaseConfig(),
    )
    assert payload["ok"] is True
    assert payload["intent"] == "crop_choice"
    assert payload["market_intelligence"]["crop_options"]["ok"] is True
    assert payload["recommended_actions"], "crop choice must state an action"


def test_copilot_market_turn_survives_a_provider_outage(market_farmer, monkeypatch):
    from agriq.integrations.ai import gemini
    from agriq.services import copilot_orchestrator, market_service

    class FakeResult:
        available = True
        text = "Answer."
        error_category = None

    monkeypatch.setattr(gemini, "generate", lambda *args, **kwargs: FakeResult())

    def boom(*args, **kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(market_service, "get_mandi_prices", boom)
    payload = copilot_orchestrator.run_copilot(
        user_id=1, profile_id=1, question="What is the mandi price of rice?",
        field_id=market_farmer["field"]["id"], crop_cycle_id=market_farmer["cycle"]["id"],
        config=copilot_orchestrator.BaseConfig(),
    )
    assert payload["ok"] is True
    assert payload["answer"]
    # No fabricated price reaches the answer or the actions.
    assert "₹" not in (payload["recommended_actions"] or [""])[0]
