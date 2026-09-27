"""Phase 7.3 integration tests: the dashboard must report the REAL data state.

Regression focus
----------------
The "Data Source and Freshness" panel used to be structurally unable to tell the
truth: the dashboard built the farmer context with ``include_weather=False``, so
its weather chip said "Verified data is currently unavailable." on every load no
matter how healthy the provider was, while the mandi chip rendered a fixed
sentence. These tests pin the corrected behaviour: a healthy provider is
reported as healthy, a failure names its cause, and a missing credential is
configuration — never fake data.

All rows created here live in the TEST database; the weather/mandi payloads are
TEST FIXTURES and are never used as production fallback data.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
import requests

from agriq.core.time import utc_now
from agriq.extensions import db
from agriq.models.farmer import MarketPriceRecord
from agriq.services import farmer_context, market_service, weather_service

TEST_HEADERS = {"X-CSRF-Token": "test-csrf-token"}


@pytest.fixture(autouse=True)
def _clean_weather_cache():
    """The integration's payload cache is process-wide; isolate each test."""
    weather_service.open_meteo._cache.clear()
    yield
    weather_service.open_meteo._cache.clear()


@pytest.fixture()
def farmer_without_coordinates(auth_client):
    """Farmer with a profile + farm but NO stored coordinates (test fixture)."""
    client = auth_client
    client.post("/api/profile", json={
        "full_name": "Test Farmer", "state": "Odisha", "district": "Cuttack",
        "preferred_language": "en",
    }, headers=TEST_HEADERS)
    client.post("/api/farms", json={"name": "No-GPS Farm", "district": "Cuttack"},
                headers=TEST_HEADERS)
    return client


def _live_weather(lat=20.4625, lon=85.883):
    """TEST FIXTURE shaped exactly like a parsed Open-Meteo payload."""
    return {
        "available": True, "live": True, "provider": "Open-Meteo", "reason": None,
        "state": "OK", "state_message": None,
        "provider_observed_at": utc_now().isoformat(), "retrieved_at": utc_now().isoformat(),
        "temp": 31.5, "humidity": 68.0, "rain": 0.0, "precipitation": 0.0,
        "wind": 9.0, "condition": "Partly cloudy", "weather_code": 2,
        "hourly": [], "daily": [], "history": [],
    }


# ---------------------------------------------------------------------------
# Market service states
# ---------------------------------------------------------------------------

def test_no_credential_reports_configuration_error_without_faking_a_price(app):
    with app.app_context():
        payload = market_service.get_mandi_prices("Rice", district="Cuttack")
    assert payload["available"] is False
    assert payload["state"] == "CONFIGURATION_ERROR"
    assert payload["reason"] == "api_key_not_configured"
    assert payload["credential_configured"] is False
    assert payload["records"] == []
    # Names the variable so the deployment can act, and never a value.
    assert "DATA_GOV_IN_API_KEY" in payload["state_message"]
    # Backwards-compatible canonical sentence still present.
    assert payload["message"] == "Verified data is currently unavailable."


def test_provider_failure_is_data_source_error_not_a_price(app, monkeypatch):
    app.config["DATA_GOV_IN_API_KEY"] = "test-fixture-key"

    def _boom(*a, **k):
        raise requests.ConnectionError("provider down")

    monkeypatch.setattr(requests, "get", _boom)
    with app.app_context():
        payload = market_service.get_mandi_prices("Rice", district="Cuttack")
    assert payload["state"] == "DATA_SOURCE_ERROR"
    assert payload["records"] == []
    assert "temporarily unavailable" in payload["state_message"]


def test_configured_key_never_reaches_the_response(app, monkeypatch):
    secret = "SUPER-SECRET-FIXTURE-KEY"
    app.config["DATA_GOV_IN_API_KEY"] = secret

    def _boom(*a, **k):
        raise requests.ConnectionError("provider down")

    monkeypatch.setattr(requests, "get", _boom)
    with app.app_context():
        payload = market_service.get_mandi_prices("Rice", district="Cuttack")
    body = json.dumps(payload)
    assert secret not in body
    assert "api-key" not in body
    assert "Authorization" not in body


def test_persisted_official_records_are_reported_with_their_dates(app):
    with app.app_context():
        today = utc_now().date()
        db.session.add(MarketPriceRecord(
            source="AGMARKNET via data.gov.in", state="Odisha", district="Cuttack",
            market="Chhatra Bazar", commodity="Paddy(Dhan)(Common)", variety="Common",
            arrival_date=today, minimum_price=2100.0, maximum_price=2500.0,
            modal_price=2350.0, retrieved_at=utc_now(), raw_record_hash="fixture-hash-1",
        ))
        db.session.commit()
        summary = market_service.persisted_summary(district="Cuttack")
        context = market_service.context_state(district="Cuttack", state="Odisha")

    assert summary["record_count"] == 1
    assert summary["newest_arrival_date"] == today.isoformat()
    assert context["available"] is True
    assert context["record_count"] == 1
    assert context["state"] == "OK"
    # A context read never fetches, and never claims to be live.
    assert context["fetched_live"] is False
    assert context["source"] == "AGMARKNET via data.gov.in"


def test_old_records_are_stale_and_never_current(app):
    with app.app_context():
        db.session.add(MarketPriceRecord(
            source="AGMARKNET via data.gov.in", state="Odisha", district="Sambalpur",
            market="Sambalpur", commodity="Paddy(Dhan)(Common)", variety="Common",
            arrival_date=utc_now().date() - timedelta(days=40),
            minimum_price=2000.0, maximum_price=2400.0, modal_price=2200.0,
            retrieved_at=utc_now(), raw_record_hash="fixture-hash-2",
        ))
        db.session.commit()
        context = market_service.context_state(district="Sambalpur", state="Odisha")

    assert context["state"] == "DATA_STALE"
    assert "historical" in context["state_message"].lower()


#: Age windows come from the canonical classifier (market: fresh ≤24 h, aging ≤72 h,
#: stale ≤240 h, expired beyond). Whole days are used with a margin so the
#: time-of-day cannot push a case across a boundary.
@pytest.mark.parametrize("days, expected", [
    (0, "fresh"), (2, "aging"), (9, "stale"), (60, "expired"),
])
def test_record_status_comes_from_the_canonical_classifier(app, days, expected):
    with app.app_context():
        moment = utc_now() - timedelta(days=days)
        assert market_service.record_status(moment.date().isoformat()) == expected


def test_record_status_without_a_date_is_unavailable(app):
    with app.app_context():
        assert market_service.record_status(None) == "unavailable"


# ---------------------------------------------------------------------------
# Weather service states
# ---------------------------------------------------------------------------

def test_weather_falls_back_to_the_district_centre_when_no_coordinates(app, monkeypatch):
    monkeypatch.setattr(weather_service.open_meteo, "fetch_weather",
                        lambda lat, lon, **k: _live_weather(lat, lon))
    with app.app_context():
        weather = weather_service.get_district_weather("Cuttack")
    assert weather["available"] is True
    assert weather["location_source"] == "district_centre"
    assert weather["temp"] == 31.5
    assert weather["state"] == "OK"
    assert "district administrative centre" in weather["location_basis"].lower()
    assert weather["freshness"]["freshness_status"] == "fresh"


def test_district_weather_without_a_location_is_invalid_location(app):
    with app.app_context():
        weather = weather_service.get_district_weather(None)
    assert weather["available"] is False
    assert weather["state"] == "INVALID_LOCATION"
    assert weather["temp"] is None


def test_weather_provider_failure_is_data_source_error(app, monkeypatch):
    def _fail(lat, lon, **k):
        return weather_service.open_meteo.unavailable(
            "provider_request_failed", "DATA_SOURCE_ERROR"
        )

    monkeypatch.setattr(weather_service.open_meteo, "fetch_weather", _fail)
    with app.app_context():
        weather = weather_service.get_district_weather("Cuttack")
    assert weather["available"] is False
    assert weather["state"] == "DATA_SOURCE_ERROR"
    assert weather["temp"] is None


# ---------------------------------------------------------------------------
# Farmer context
# ---------------------------------------------------------------------------

def test_farmer_context_weather_uses_the_profile_district(app, monkeypatch,
                                                          farmer_without_coordinates):
    monkeypatch.setattr(weather_service.open_meteo, "fetch_weather",
                        lambda lat, lon, **k: _live_weather(lat, lon))
    from agriq.repositories.user_repository import UserRepository

    with app.app_context():
        user = UserRepository.get_by_contact("tester@example.com")
        context = farmer_context.build_farmer_context(user.id, include_weather=True)

    assert context["weather"]["available"] is True
    assert context["weather"]["location_source"] == "district_centre"


def test_farmer_context_market_is_a_real_state_not_a_placeholder(
        app, farmer_without_coordinates):
    from agriq.repositories.user_repository import UserRepository

    with app.app_context():
        user = UserRepository.get_by_contact("tester@example.com")
        context = farmer_context.build_farmer_context(user.id, include_weather=False)

    market = context["market"]
    assert market["state"] in ("CONFIGURATION_ERROR", "DATA_UNAVAILABLE", "DATA_STALE", "OK")
    assert "credential_configured" in market
    assert market["fetched_live"] is False
    # The old placeholder shape must be gone.
    assert market.get("reason") != "not_requested" or not market.get("available")


def test_farmer_context_reports_weather_as_not_requested_when_skipped(
        app, farmer_without_coordinates):
    from agriq.repositories.user_repository import UserRepository

    with app.app_context():
        user = UserRepository.get_by_contact("tester@example.com")
        context = farmer_context.build_farmer_context(user.id, include_weather=False)
    assert context["weather"]["state"] == "DATA_UNAVAILABLE"
    assert context["weather"]["reason"] == "not_requested"
    assert context["weather"]["available"] is False


# ---------------------------------------------------------------------------
# The reported dashboard regression
# ---------------------------------------------------------------------------

def test_dashboard_reports_a_healthy_weather_provider_as_available(
        farmer_without_coordinates, monkeypatch):
    """The chip must NOT say 'unavailable' while the provider is healthy."""
    monkeypatch.setattr(weather_service.open_meteo, "fetch_weather",
                        lambda lat, lon, **k: _live_weather(lat, lon))
    html = farmer_without_coordinates.get("/dashboard").get_data(as_text=True)

    assert "Weather:" in html
    assert "Open-Meteo" in html
    chip = html.split("Weather:", 1)[1].split("</span>", 1)[0]
    assert "Verified data is currently unavailable." not in chip
    assert "district centre" in chip
    assert "updated" in chip


def test_dashboard_weather_chip_names_a_provider_failure(farmer_without_coordinates,
                                                        monkeypatch):
    def _fail(lat, lon, **k):
        return weather_service.open_meteo.unavailable(
            "provider_request_failed", "DATA_SOURCE_ERROR"
        )

    monkeypatch.setattr(weather_service.open_meteo, "fetch_weather", _fail)
    html = farmer_without_coordinates.get("/dashboard").get_data(as_text=True)
    chip = html.split("Weather:", 1)[1].split("</span>", 1)[0]
    assert "provider connection failed" in chip


def test_dashboard_mandi_chip_states_the_missing_credential(farmer_without_coordinates):
    """Without a key the chip must say so — not promise prices forever."""
    html = farmer_without_coordinates.get("/dashboard").get_data(as_text=True)
    assert "Official records shown when returned by data.gov.in." not in html
    chip = html.split("Mandi prices:", 1)[1].split("</span>", 1)[0]
    assert "DATA_GOV_IN_API_KEY" in chip


def test_dashboard_mandi_chip_reports_stored_official_records(farmer_without_coordinates):
    with farmer_without_coordinates.application.app_context():
        db.session.add(MarketPriceRecord(
            source="AGMARKNET via data.gov.in", state="Odisha", district="Cuttack",
            market="Chhatra Bazar", commodity="Paddy(Dhan)(Common)", variety="Common",
            arrival_date=utc_now().date(), minimum_price=2100.0, maximum_price=2500.0,
            modal_price=2350.0, retrieved_at=utc_now(), raw_record_hash="fixture-hash-3",
        ))
        db.session.commit()
    html = farmer_without_coordinates.get("/dashboard").get_data(as_text=True)
    chip = html.split("Mandi prices:", 1)[1].split("</span>", 1)[0]
    assert "official record" in chip
    assert "newest arrival date" in chip
    assert "OK" in chip
