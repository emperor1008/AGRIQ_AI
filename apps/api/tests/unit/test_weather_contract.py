"""Weather integration contract tests (Phase 1 real-data policy).

Proves: no deterministic/seasonal fallback exists in the production module,
provider failure yields an explicit unavailable state, and snapshots carry
full provenance.
"""
from __future__ import annotations

import inspect

import pytest
import requests

from agriq.integrations.weather import open_meteo


@pytest.fixture(autouse=True)
def _clean_cache():
    open_meteo._cache.clear()
    yield
    open_meteo._cache.clear()


def test_deterministic_weather_removed_from_production_module():
    """The offline seasonal model must not exist in the production module."""
    assert not hasattr(open_meteo, "deterministic_weather"), (
        "deterministic weather fallback must be removed from production"
    )


def test_unavailable_payload_has_no_generated_values():
    payload = open_meteo.unavailable("provider_request_failed")
    assert payload["available"] is False
    assert payload["temp"] is None
    assert payload["humidity"] is None
    assert payload["rain"] is None
    assert payload["wind"] is None
    assert payload["message"] == "Verified data is currently unavailable."
    assert payload["records"] if "records" in payload else True


def test_get_weather_returns_unavailable_when_provider_down(monkeypatch):
    def _boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", _boom)
    result = open_meteo.get_weather("Cuttack")
    assert result["available"] is False
    assert result["reason"] == "provider_request_failed"


def test_get_weather_by_coordinates(monkeypatch):
    payload = {
        "current": {
            "time": "2026-09-22T10:00",
            "temperature_2m": 27.8,
            "relative_humidity_2m": 88,
            "rain": 0.0,
            "weather_code": 2,
            "wind_speed_10m": 7.5,
        },
        "hourly": {"time": ["2026-09-22T10:00"], "temperature_2m": [27.8],
                   "relative_humidity_2m": [88], "precipitation_probability": [12],
                   "rain": [0.0], "weather_code": [2], "wind_speed_10m": [7.5]},
        "daily": {"time": ["2026-09-22"], "weather_code": [2],
                  "temperature_2m_max": [31.0], "temperature_2m_min": [24.0],
                  "precipitation_sum": [0.4], "precipitation_probability_max": [15],
                  "wind_speed_10m_max": [9.0]},
    }

    class FakeResponse:
        def raise_for_status(self): ...
        def json(self): return payload

    captured = {}

    def fake_get(url, params=None, **kwargs):
        captured["params"] = params
        return FakeResponse()

    monkeypatch.setattr(requests, "get", fake_get)
    result = open_meteo.get_weather(lat=20.46, lon=85.88)
    assert result["available"] is True
    assert result["temp"] == 27.8
    # coordinates passed through to the provider request
    assert captured["params"]["latitude"] == 20.46
    assert captured["params"]["longitude"] == 85.88
    assert result["provider_observed_at"] == "2026-09-22T10:00"
    assert result["retrieved_at"]  # retrieval timestamp recorded


def test_retry_then_success(monkeypatch):
    """One safe retry: first attempt fails, second succeeds."""
    payload = {
        "current": {"time": "2026-09-22T10:00", "temperature_2m": 30.0,
                    "relative_humidity_2m": 70, "rain": 0, "weather_code": 1,
                    "wind_speed_10m": 8.0},
        "hourly": {"time": ["2026-09-22T10:00"], "temperature_2m": [30.0],
                   "relative_humidity_2m": [70], "precipitation_probability": [5],
                   "rain": [0], "weather_code": [1], "wind_speed_10m": [8.0]},
        "daily": {"time": ["2026-09-22"], "weather_code": [1],
                  "temperature_2m_max": [33.0], "temperature_2m_min": [25.0],
                  "precipitation_sum": [0.0], "precipitation_probability_max": [5],
                  "wind_speed_10m_max": [10.0]},
    }

    class FakeResponse:
        def raise_for_status(self): ...
        def json(self): return payload

    calls = {"n": 0}

    def flaky_get(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.Timeout("first attempt times out")
        return FakeResponse()

    monkeypatch.setattr(requests, "get", flaky_get)
    monkeypatch.setattr(open_meteo.time, "sleep", lambda s: None)
    result = open_meteo.get_weather("Puri")
    assert result["available"] is True
    assert calls["n"] == 2


def test_client_error_not_retried(monkeypatch):
    class Fake400:
        status_code = 400

        def raise_for_status(self):
            error = requests.HTTPError("bad request")
            error.response = self
            raise error

        def json(self): return {}

    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        return Fake400()

    monkeypatch.setattr(requests, "get", fake_get)
    result = open_meteo.fetch_live_weather(20.4, 85.8)
    assert result is None
    assert calls["n"] == 1  # no retry on 4xx


def test_missing_provider_fields_stay_none(monkeypatch):
    payload = {
        "current": {"time": "2026-09-22T10:00", "weather_code": 3},
        "hourly": {"time": ["2026-09-22T10:00"]},
        "daily": {"time": ["2026-09-22"]},
    }

    class FakeResponse:
        def raise_for_status(self): ...
        def json(self): return payload

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    result = open_meteo.get_weather("Cuttack")
    assert result["available"] is True
    assert result["temp"] is None  # provider did not return it — stays unknown
    assert result["humidity"] is None
