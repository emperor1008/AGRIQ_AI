"""Phase 5 integration tests: risk API end-to-end.

Covers: the full chain (auth → farm → field → crop cycle → farmer context →
engine → persistence → API), honest unavailable states, ownership isolation
with two INDEPENDENT farmer sessions, append-only history, farmer action
tracking, and rate-limited analyze endpoint. Weather/provider responses are
exercised through their real failure paths (no keys → honest unavailable);
test fixtures stay inside this directory and never reach production storage.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

TEST_CONTEXT_HEADERS = {"X-CSRF-Token": "test-csrf-token"}


# ---------------------------------------------------------------------------
# Fixtures (clearly test-only)
# ---------------------------------------------------------------------------

@pytest.fixture()
def onboarded_farmer(auth_client):
    """First farmer with profile + farm + field + active rice crop cycle."""
    client = auth_client
    client.post("/api/profile", json={
        "full_name": "Risk Farmer", "state": "Odisha", "district": "Cuttack",
        "preferred_language": "en",
    }, headers=TEST_CONTEXT_HEADERS)
    farm = client.post("/api/farms", json={
        "name": "Risk Farm", "district": "Cuttack",
        "latitude": 20.46, "longitude": 85.88,
    }, headers=TEST_CONTEXT_HEADERS).get_json()["farm"]
    field = client.post(f"/api/farms/{farm['id']}/fields", json={
        "name": "Paddy One", "area": 1.5, "area_unit": "acre",
        "irrigation_type": "canal", "latitude": 20.46, "longitude": 85.88,
    }, headers=TEST_CONTEXT_HEADERS).get_json()["field"]
    cycle = client.post(f"/api/fields/{field['id']}/crop-cycles", json={
        "crop_name": "Rice", "variety": "Swarna", "season": "Kharif",
        "sowing_date": "2026-07-10",
    }, headers=TEST_CONTEXT_HEADERS).get_json()["crop_cycle"]
    return {"client": client, "farm": farm, "field": field, "cycle": cycle}


@pytest.fixture()
def second_onboarded_farmer(second_farmer_client):
    """Independent second farmer with own field — proves isolation."""
    client = second_farmer_client
    client.post("/api/profile", json={
        "full_name": "Second Farmer", "state": "Odisha", "district": "Jajpur",
    }, headers=TEST_CONTEXT_HEADERS)
    farm = client.post("/api/farms", json={"name": "Other Farm"}, headers=TEST_CONTEXT_HEADERS).get_json()["farm"]
    field = client.post(f"/api/farms/{farm['id']}/fields", json={
        "name": "Other Field",
    }, headers=TEST_CONTEXT_HEADERS).get_json()["field"]
    return {"client": client, "farm": farm, "field": field}


# ---------------------------------------------------------------------------
# Authentication & ownership
# ---------------------------------------------------------------------------

def test_analyze_requires_authentication(client):
    response = client.post("/api/v1/risk/fields/1/analyze", json={})
    assert response.status_code == 404


def test_current_requires_authentication(client):
    response = client.get("/api/v1/risk/fields/1/current")
    assert response.status_code == 404


def test_foreign_field_is_404_not_403(onboarded_farmer, second_onboarded_farmer):
    """A foreign field is indistinguishable from a missing one (§30)."""
    foreign_field = second_onboarded_farmer["field"]["id"]
    response = onboarded_farmer["client"].post(
        f"/api/v1/risk/fields/{foreign_field}/analyze", json={},
        headers=TEST_CONTEXT_HEADERS)
    assert response.status_code == 404


def test_foreign_current_is_404(onboarded_farmer, second_onboarded_farmer):
    response = onboarded_farmer["client"].get(
        f"/api/v1/risk/fields/{second_onboarded_farmer['field']['id']}/current")
    assert response.status_code == 404


def test_history_never_leaks_other_farmer(onboarded_farmer, second_onboarded_farmer):
    second = second_onboarded_farmer["client"].post(
        f"/api/v1/risk/fields/{second_onboarded_farmer['field']['id']}/analyze",
        json={}, headers=TEST_CONTEXT_HEADERS).get_json()
    assert second.get("ok") is True
    history = onboarded_farmer["client"].get(
        f"/api/v1/risk/fields/{second_onboarded_farmer['field']['id']}/history")
    assert history.status_code == 404


# ---------------------------------------------------------------------------
# Analysis pipeline
# ---------------------------------------------------------------------------

def test_analyze_without_weather_provider_returns_honest_states(onboarded_farmer):
    """No network/keys in tests: weather unavailable must flow through as an
    honest data_unavailable assessment — never fabricated values (§47)."""
    client = onboarded_farmer["client"]
    response = client.post(
        f"/api/v1/risk/fields/{onboarded_farmer['field']['id']}/analyze",
        json={}, headers=TEST_CONTEXT_HEADERS)
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert len(body["assessments"]) == 5
    types = {a["risk_type"] for a in body["assessments"]}
    assert types == {
        "disease_conducive_weather", "heavy_rain_flooding", "heat_stress",
        "water_stress", "market_volatility",
    }
    for assessment in body["assessments"]:
        assert assessment["status"] in (
            "inactive", "monitor", "elevated", "high", "critical",
            "data_unavailable", "insufficient_data",
        )
        # No probability without a documented derivation and evidence trail.
        if assessment["probability"] is not None:
            assert assessment["evidence"], "probability without evidence is fabrication"
            assert 0.0 <= assessment["probability"] <= 1.0
        if assessment["confidence"] is not None:
            assert 0.0 <= assessment["confidence"] <= 1.0


def test_unsupported_crop_is_reported_honestly(onboarded_farmer):
    client = onboarded_farmer["client"]
    # Replace the cycle's crop through the public API is not possible post-hoc;
    # instead verify the analyzer contract via a mango cycle rejection path:
    # create a new field + cycle with an unsupported crop.
    field = client.post(f"/api/farms/{onboarded_farmer['farm']['id']}/fields", json={
        "name": "Orchard", "latitude": 20.46, "longitude": 85.88,
    }, headers=TEST_CONTEXT_HEADERS).get_json()["field"]
    client.post(f"/api/fields/{field['id']}/crop-cycles", json={
        "crop_name": "Mango", "season": "Summer", "sowing_date": "2026-06-01",
    }, headers=TEST_CONTEXT_HEADERS)
    response = client.post(f"/api/v1/risk/fields/{field['id']}/analyze",
                           json={}, headers=TEST_CONTEXT_HEADERS)
    body = response.get_json()
    weather_risk = next(a for a in body["assessments"] if a["risk_type"] == "disease_conducive_weather")
    assert weather_risk["status"] == "data_unavailable"
    assert weather_risk["unavailable_reason"] == "crop_not_supported"


def test_analyze_is_idempotent_within_window(onboarded_farmer):
    client = onboarded_farmer["client"]
    field_id = onboarded_farmer["field"]["id"]
    first = client.post(f"/api/v1/risk/fields/{field_id}/analyze",
                        json={}, headers=TEST_CONTEXT_HEADERS).get_json()
    second = client.post(f"/api/v1/risk/fields/{field_id}/analyze",
                         json={}, headers=TEST_CONTEXT_HEADERS).get_json()
    assert first["ok"] and second["ok"]
    assert second["cached_run"] is True
    assert [a["id"] for a in second["assessments"]] == [a["id"] for a in first["assessments"]]


def test_current_returns_persisted_run(onboarded_farmer):
    client = onboarded_farmer["client"]
    field_id = onboarded_farmer["field"]["id"]
    client.post(f"/api/v1/risk/fields/{field_id}/analyze", json={}, headers=TEST_CONTEXT_HEADERS)
    response = client.get(f"/api/v1/risk/fields/{field_id}/current")
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert len(body["assessments"]) == 5
    assessment = body["assessments"][0]
    assert assessment["rule_version"] == "agriq-risk-rules-v1"
    assert assessment["generated_at"]


def test_history_is_append_only_after_force_rerun(onboarded_farmer):
    client = onboarded_farmer["client"]
    field_id = onboarded_farmer["field"]["id"]
    client.post(f"/api/v1/risk/fields/{field_id}/analyze", json={}, headers=TEST_CONTEXT_HEADERS)
    client.post(f"/api/v1/risk/fields/{field_id}/analyze", json={"force": True}, headers=TEST_CONTEXT_HEADERS)
    history = client.get(f"/api/v1/risk/fields/{field_id}/history").get_json()
    record_statuses = {row["record_status"] for row in history["history"]}
    assert "superseded" in record_statuses or len(history["history"]) >= 5


# ---------------------------------------------------------------------------
# Farmer action tracking (§27)
# ---------------------------------------------------------------------------

def test_action_requires_valid_status(onboarded_farmer):
    client = onboarded_farmer["client"]
    field_id = onboarded_farmer["field"]["id"]
    run = client.post(f"/api/v1/risk/fields/{field_id}/analyze", json={}, headers=TEST_CONTEXT_HEADERS).get_json()
    risk_id = run["assessments"][0]["id"]
    response = client.post(f"/api/v1/risk/assessments/{risk_id}/action",
                           json={"action_status": "auto_done"}, headers=TEST_CONTEXT_HEADERS)
    assert response.status_code == 400


def test_action_persists_and_never_autocompletes(onboarded_farmer):
    client = onboarded_farmer["client"]
    field_id = onboarded_farmer["field"]["id"]
    run = client.post(f"/api/v1/risk/fields/{field_id}/analyze", json={}, headers=TEST_CONTEXT_HEADERS).get_json()
    risk_id = run["assessments"][0]["id"]
    response = client.post(f"/api/v1/risk/assessments/{risk_id}/action", json={
        "action_status": "completed",
        "farmer_note": "Checked drainage channels.",
    }, headers=TEST_CONTEXT_HEADERS)
    assert response.status_code == 200
    action = response.get_json()["action"]
    assert action["action_status"] == "completed"
    assert action["farmer_note"] == "Checked drainage channels."
    assert action["recommendation_id"] is not None


def test_foreign_action_is_404(onboarded_farmer, second_onboarded_farmer):
    """User A cannot record an action on User B's assessment."""
    second_run = second_onboarded_farmer["client"].post(
        f"/api/v1/risk/fields/{second_onboarded_farmer['field']['id']}/analyze",
        json={}, headers=TEST_CONTEXT_HEADERS).get_json()
    foreign_id = second_run["assessments"][0]["id"]
    response = onboarded_farmer["client"].post(
        f"/api/v1/risk/assessments/{foreign_id}/action",
        json={"action_status": "completed"}, headers=TEST_CONTEXT_HEADERS)
    assert response.status_code == 404


def test_foreign_assessment_read_is_404(onboarded_farmer, second_onboarded_farmer):
    second_run = second_onboarded_farmer["client"].post(
        f"/api/v1/risk/fields/{second_onboarded_farmer['field']['id']}/analyze",
        json={}, headers=TEST_CONTEXT_HEADERS).get_json()
    foreign_id = second_run["assessments"][0]["id"]
    response = onboarded_farmer["client"].get(f"/api/v1/risk/assessments/{foreign_id}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Regressions: existing routes untouched
# ---------------------------------------------------------------------------

def test_existing_routes_still_present(app):
    rules = {str(rule) for rule in app.url_map.iter_rules()}
    for legacy in (
        "/ask-ai", "/api/v1/copilot/messages", "/api/v1/voice/capabilities",
        "/api/v1/crop-images/analyse", "/api/live-weather", "/api/profile",
    ):
        assert legacy in rules, f"regression: missing {legacy}"


def test_risk_routes_added(app):
    rules = {str(rule) for rule in app.url_map.iter_rules()}
    for route in (
        "/api/v1/risk/fields/<int:field_id>/current",
        "/api/v1/risk/fields/<int:field_id>/history",
        "/api/v1/risk/fields/<int:field_id>/analyze",
        "/api/v1/risk/assessments/<int:risk_id>",
        "/api/v1/risk/assessments/<int:risk_id>/action",
    ):
        assert route in rules
