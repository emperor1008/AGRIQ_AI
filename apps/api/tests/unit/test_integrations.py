"""Integration layer unit tests: weather, Gemini, market (ARC-05, ARC-06).

Key rule under test: provider failure yields an explicit unavailable state
or clearly-labelled offline model — never fabricated "live" data.
"""
from __future__ import annotations

import pytest
import requests

from agriq.integrations.weather import open_meteo
from agriq.integrations.ai import gemini
from agriq.integrations.market import agmarknet


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

def test_weather_live_when_provider_responds(monkeypatch):
    payload = {
        "current": {
            "time": "2026-09-22T10:00",
            "temperature_2m": 29.4,
            "relative_humidity_2m": 81,
            "rain": 0.5,
            "weather_code": 3,
            "wind_speed_10m": 9.1,
        },
        "hourly": {"time": ["2026-09-22T10:00"], "temperature_2m": [29.4],
                   "relative_humidity_2m": [81], "precipitation_probability": [10],
                   "rain": [0.5], "weather_code": [3], "wind_speed_10m": [9.1]},
        "daily": {"time": ["2026-09-22"], "weather_code": [3],
                  "temperature_2m_max": [32.0], "temperature_2m_min": [25.0],
                  "precipitation_sum": [1.2], "precipitation_probability_max": [30],
                  "wind_speed_10m_max": [10.0]},
    }

    class FakeResponse:
        def raise_for_status(self): ...
        def json(self): return payload

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    open_meteo._cache.clear()
    weather = open_meteo.get_weather("Cuttack")
    assert weather["live"] is True
    assert weather["temp"] == 29.4
    assert len(weather["daily"]) == 1


def test_weather_failure_returns_unavailable_not_fabricated(monkeypatch):
    """Phase 1: provider failure yields an explicit unavailable state; the
    offline seasonal model is REMOVED from production execution."""
    def _boom(*a, **k):
        raise requests.ConnectionError("provider down")

    monkeypatch.setattr(requests, "get", _boom)
    open_meteo._cache.clear()
    weather = open_meteo.get_weather("Cuttack")
    assert weather["available"] is False
    assert weather["live"] is False
    assert weather["temp"] is None  # no generated value
    assert weather["message"] == "Verified data is currently unavailable."
    open_meteo._cache.clear()


def test_forecast_from_daily_rows():
    base = {
        "humidity": 75,
        "daily": [{"day": "23 Sep", "temp_max": 32.0, "temp_min": 24.0,
                   "rain": 3.0, "pop": 25, "wind": 9.0, "condition": "Partly cloudy"}],
    }
    rows = open_meteo.forecast_weather(base)
    assert len(rows) == 1
    assert rows[0]["temp"] == 28.0
    assert rows[0]["day"] == "23 Sep"


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def test_gemini_unconfigured_returns_none(monkeypatch):
    assert gemini.is_configured("") is False
    assert gemini.generate_answer("q", "farmer", {}, api_key="", model="m") is None


def test_gemini_configured_success(monkeypatch):
    class FakeResponse:
        def raise_for_status(self): ...
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "Gemini reply"}]}}]}

    monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResponse())
    answer = gemini.generate_answer("q", "farmer", {}, api_key="k", model="m")
    assert answer == "Gemini reply"


def test_gemini_failure_returns_none_not_scripted(monkeypatch):
    def _boom(*a, **k):
        raise requests.Timeout("provider down")

    monkeypatch.setattr(requests, "post", _boom)
    assert gemini.generate_answer("q", "farmer", {}, api_key="k", model="m") is None


def test_gemini_prompt_has_no_api_key(monkeypatch):
    captured = {}

    def fake_post(url, *a, **k):
        captured["url"] = url
        raise AssertionError("stop before network")

    monkeypatch.setattr(requests, "post", fake_post)
    prompt = gemini._prompt("hello", "farmer", {})
    assert "hello" in prompt


# ---------------------------------------------------------------------------
# Market (AGMARKNET)
# ---------------------------------------------------------------------------

def test_market_unavailable_without_key():
    result = agmarknet.fetch_mandi_prices(api_key=None, commodity="Rice", district="Cuttack")
    assert result["available"] is False
    assert result["reason"] == "api_key_not_configured"
    assert result["records"] == []  # explicit empty list, never generated rows


def test_market_unavailable_on_provider_failure(monkeypatch):
    def _boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", _boom)
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Rice", district="Cuttack")
    assert result["available"] is False
    assert result["reason"] == "provider_request_failed"


def test_market_success_returns_records_with_provider_label(monkeypatch):
    class FakeResponse:
        def raise_for_status(self): ...
        def json(self):
            return {"records": [{"commodity": "Rice", "modal_price": "2500"}], "updated_date": "2026-09-21"}

    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse())
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Rice", district="Cuttack")
    assert result["available"] is True
    assert result["provider"] == "AGMARKNET via data.gov.in"
