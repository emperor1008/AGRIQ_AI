"""Phase 7.3 real-data reliability: provider states, classification, freshness.

Every test in this module asserts the same two invariants:

1. a provider failure (timeout, HTTP error, malformed body, missing credential)
   becomes an explicit, machine-readable STATE — never a value; and
2. a successful response is passed through exactly as the provider returned it,
   with provenance that starts from AGRIQ's own retrieval time.

The payloads below are TEST FIXTURES. They exist only inside the test suite and
are never used as production fallback data.
"""
from __future__ import annotations

import json

import pytest
import requests

from agriq.core.constants import (
    MANDI_CREDENTIAL_MESSAGE,
    STATE_CONFIGURATION_ERROR,
    STATE_DATA_SOURCE_ERROR,
    STATE_INVALID_LOCATION,
    STATE_NO_OFFICIAL_RECORD,
)
from agriq.integrations.market import agmarknet
from agriq.integrations.weather import open_meteo


@pytest.fixture(autouse=True)
def _clean_weather_cache():
    open_meteo._cache.clear()
    yield
    open_meteo._cache.clear()


class FakeResponse:
    """Minimal stand-in for a requests response (test fixture).

    ``text`` mirrors the body the way a real response would, because the market
    integration classifies a 400 whose body names an authorisation problem.
    """

    def __init__(self, payload, status_code=200, text=None):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else (
            json.dumps(payload) if payload is not None else ""
        )

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"status {self.status_code}")
            error.response = self
            raise error

    def json(self):
        if self._payload is None:
            raise ValueError("malformed json")
        return self._payload


def _weather_payload(temp=29.4, code=2):
    return {
        "current": {
            "time": "2026-09-27T10:00",
            "temperature_2m": temp,
            "relative_humidity_2m": 74,
            "rain": 0.0,
            "weather_code": code,
            "wind_speed_10m": 8.0,
        },
        "hourly": {"time": ["2026-09-27T10:00"], "temperature_2m": [temp]},
        "daily": {"time": ["2026-09-27"], "temperature_2m_max": [31.0],
                  "temperature_2m_min": [24.0]},
    }


def _mandi_payload(records, updated_date="2026-09-27T09:00:00+05:30", total=None):
    payload = {"records": records, "updated_date": updated_date}
    if total is not None:
        payload["total"] = total
    return payload


def _record(index: int = 0, modal="2400.00", arrival="2026-09-26"):
    return {
        "state": "Odisha", "district": "Cuttack", "market": f"Market {index}",
        "commodity": "Paddy(Dhan)(Common)", "variety": "Common",
        "arrival_date": arrival, "min_price": "2100", "max_price": "2500",
        "modal_price": modal,
    }


# ---------------------------------------------------------------------------
# Weather — coordinate and location validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lat, lon", [(None, 85.0), (20.0, None), (0, 0),
                                      (95.0, 85.0), (20.0, 200.0), ("x", 85.0)])
def test_validate_coordinates_rejects_unusable_locations(lat, lon):
    assert open_meteo.validate_coordinates(lat, lon) is not None


def test_validate_coordinates_accepts_real_coordinates():
    assert open_meteo.validate_coordinates(20.4625, 85.883) is None


def test_missing_location_is_invalid_location_state(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no request"))
    result = open_meteo.get_weather(district=None)
    assert result["available"] is False
    assert result["state"] == STATE_INVALID_LOCATION
    assert result["temp"] is None


def test_unknown_district_never_resolves_to_another_district(monkeypatch):
    """An unrecognised name must not silently become Cuttack's weather."""
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no request"))
    result = open_meteo.get_weather("Atlantis")
    assert result["state"] == STATE_INVALID_LOCATION
    assert result["available"] is False
    assert result["temp"] is None
    # No coordinates at all: nothing was queried for a substituted location.
    assert "latitude" not in result


# ---------------------------------------------------------------------------
# Weather — failure classification
# ---------------------------------------------------------------------------

def test_timeout_is_data_source_error(monkeypatch):
    def _timeout(*a, **k):
        raise requests.Timeout("slow")

    monkeypatch.setattr(requests, "get", _timeout)
    result = open_meteo.fetch_weather(20.46, 85.88)
    assert result["available"] is False
    assert result["state"] == STATE_DATA_SOURCE_ERROR
    assert result["reason"] == "provider_timeout"
    assert result["temp"] is None and result["daily"] == []
    assert "provider connection failed" in result["state_message"]


def test_provider_5xx_is_data_source_error_and_is_retried(monkeypatch):
    calls = {"n": 0}

    def _get(*a, **k):
        calls["n"] += 1
        return FakeResponse(None, status_code=503)

    monkeypatch.setattr(requests, "get", _get)
    result = open_meteo.fetch_weather(20.46, 85.88)
    assert result["state"] == STATE_DATA_SOURCE_ERROR
    assert result["reason"] == "provider_http_error"
    assert calls["n"] == open_meteo.MAX_RETRIES + 1


def test_provider_4xx_is_not_retried(monkeypatch):
    calls = {"n": 0}

    def _get(*a, **k):
        calls["n"] += 1
        return FakeResponse(None, status_code=400)

    monkeypatch.setattr(requests, "get", _get)
    result = open_meteo.fetch_weather(20.46, 85.88)
    assert result["state"] == STATE_DATA_SOURCE_ERROR
    assert calls["n"] == 1


def test_malformed_json_is_classified(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(None))
    result = open_meteo.fetch_weather(20.46, 85.88)
    assert result["reason"] == "provider_malformed_response"
    assert result["state"] == STATE_DATA_SOURCE_ERROR


def test_payload_without_sections_is_malformed(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse({"unexpected": 1}))
    result = open_meteo.fetch_weather(20.46, 85.88)
    assert result["reason"] == "provider_malformed_response"


def test_sparse_payload_is_returned_as_retrieved(monkeypatch):
    """Missing provider fields stay None; they are never invented."""
    payload = {"current": {"time": "2026-09-27T10:00", "weather_code": 3},
               "hourly": {"time": ["2026-09-27T10:00"]},
               "daily": {"time": ["2026-09-27"]}}
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(payload))
    result = open_meteo.get_weather("Cuttack")
    assert result["available"] is True
    assert result["temp"] is None
    assert result["humidity"] is None


def test_successful_response_carries_location_and_provenance(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(_weather_payload()))
    result = open_meteo.get_weather("Khordha", location_source="district_centre")
    assert result["available"] is True
    assert result["temp"] == 29.4
    assert result["provider"] == "Open-Meteo"
    assert result["location_source"] == "district_centre"
    assert result["latitude"] == 20.182 and result["longitude"] == 85.616
    assert result["retrieved_at"]


def test_district_lookup_is_case_insensitive_but_exact(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(_weather_payload()))
    assert open_meteo.get_weather("khordha")["available"] is True
    assert open_meteo.get_weather("atlantis")["state"] == STATE_INVALID_LOCATION


# ---------------------------------------------------------------------------
# Weather — freshness
# ---------------------------------------------------------------------------

def test_freshness_of_payload_without_timestamp_is_unavailable():
    payload = {"available": True, "retrieved_at": None, "provider_observed_at": None}
    freshness = open_meteo.freshness(payload, ttl_seconds=1800)
    assert freshness["freshness_status"] == "unavailable"
    assert freshness["is_stale"] is True


def test_freshness_marks_old_retrieval_stale():
    payload = {
        "available": True,
        "retrieved_at": "2020-01-01T00:00:00+00:00",
        "provider_observed_at": "2020-01-01T00:00",
    }
    freshness = open_meteo.freshness(payload, ttl_seconds=1800)
    assert freshness["freshness_status"] in ("stale", "expired")
    assert freshness["is_stale"] is True


def test_freshness_of_a_just_retrieved_payload_is_fresh():
    result = open_meteo.unavailable("provider_request_failed")
    assert open_meteo.freshness(result, 1800)["freshness_status"] == "unavailable"


# ---------------------------------------------------------------------------
# Mandi — credential handling
# ---------------------------------------------------------------------------

def test_missing_api_key_is_configuration_error_without_network_call(monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: pytest.fail("no request may be attempted")
    )
    result = agmarknet.fetch_mandi_prices(api_key="", commodity="Paddy(Common)")
    assert result["available"] is False
    assert result["state"] == STATE_CONFIGURATION_ERROR
    assert result["reason"] == "api_key_not_configured"
    assert "DATA_GOV_IN_API_KEY" in result["state_message"]
    assert result["records"] == []


def test_blank_commodity_is_rejected_before_any_request(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("no request"))
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="  ")
    assert result["available"] is False


def test_provider_403_is_classified_as_a_credential_problem(monkeypatch):
    monkeypatch.setattr(
        requests, "get",
        lambda *a, **k: FakeResponse({"error": "invalid key"}, status_code=403),
    )
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Paddy(Common)")
    assert result["state"] == STATE_CONFIGURATION_ERROR
    assert result["reason"] == "api_key_not_configured"


def test_provider_400_authorization_body_is_a_credential_problem(monkeypatch):
    """data.gov.in answers a keyless call with 400 + 'Authorization field missing'."""
    monkeypatch.setattr(
        requests, "get",
        lambda *a, **k: FakeResponse({"error": "Authorization field missing"},
                                     status_code=400),
    )
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Paddy(Common)")
    assert result["reason"] == "api_key_not_configured"


def test_provider_5xx_is_data_source_error(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(None, status_code=502))
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Paddy(Common)")
    assert result["state"] == STATE_DATA_SOURCE_ERROR
    assert result["records"] == []


def test_timeout_is_data_source_error(monkeypatch):
    def _timeout(*a, **k):
        raise requests.Timeout("slow")

    monkeypatch.setattr(requests, "get", _timeout)
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Paddy(Common)")
    assert result["reason"] == "provider_timeout"


# ---------------------------------------------------------------------------
# Mandi — parsing, pagination, normalization, provenance
# ---------------------------------------------------------------------------

def test_provider_records_are_parsed_and_normalized(monkeypatch):
    payload = _mandi_payload([_record(0, modal="2400.00")])
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(payload))
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Paddy(Common)",
                                          district="Cuttack")
    assert result["available"] is True
    assert result["state"] == "OK"
    record = result["records"][0]
    assert record["commodity"] == "Paddy(Dhan)(Common)"
    assert record["modal_price"] == 2400.0
    assert record["min_price"] == 2100.0
    assert record["arrival_date"] == "2026-09-26"


def test_rs_suffixed_provider_fields_are_accepted(monkeypatch):
    """Regression: prices must survive the provider's alternative field names."""
    record = {
        "state": "Odisha", "district": "Cuttack", "market": "Chhatra Bazar",
        "commodity": "Rice", "variety": "Common", "arrival_date": "2026-09-26",
        "min_price_rs": "2,100", "max_price_rs": "2500", "modal_price_rs": "2,350.5",
    }
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(_mandi_payload([record])))
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Rice")
    record_out = result["records"][0]
    assert record_out["min_price"] == 2100.0
    assert record_out["max_price"] == 2500.0
    assert record_out["modal_price"] == 2350.5


def test_zero_price_is_not_a_price(monkeypatch):
    record = _record(0, modal="0")
    record["min_price"] = 0
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(_mandi_payload([record])))
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Paddy(Common)")
    assert result["records"][0]["modal_price"] is None
    assert result["records"][0]["min_price"] is None


def test_unavailable_price_fields_stay_none(monkeypatch):
    record = _record(0)
    record.update({"min_price": "NA", "max_price": "", "modal_price": "0"})
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(_mandi_payload([record])))
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Paddy(Common)")
    assert result["records"][0]["min_price"] is None
    assert result["records"][0]["max_price"] is None
    assert result["records"][0]["modal_price"] is None


def test_pagination_is_bounded_and_pages_are_collected(monkeypatch):
    offsets: list[int] = []
    full_page = [_record(i) for i in range(agmarknet.PARAM_LIMIT)]

    def _get(url, params=None, **kwargs):
        offsets.append(params["offset"])
        return FakeResponse(_mandi_payload(full_page if params["offset"] == 0
                                           else [_record(0), _record(1)]))

    monkeypatch.setattr(requests, "get", _get)
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Paddy(Common)")
    assert offsets == [0, agmarknet.PARAM_LIMIT]
    assert len(result["records"]) == agmarknet.PARAM_LIMIT + 2


def test_pagination_stops_at_max_pages(monkeypatch):
    calls = {"n": 0}

    def _get(url, params=None, **kwargs):
        calls["n"] += 1
        return FakeResponse(_mandi_payload([_record(i) for i in range(agmarknet.PARAM_LIMIT)]))

    monkeypatch.setattr(requests, "get", _get)
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Paddy(Common)")
    assert calls["n"] == agmarknet.MAX_PAGES
    assert len(result["records"]) == agmarknet.PARAM_LIMIT * agmarknet.MAX_PAGES


def test_zero_records_is_a_no_official_record_state(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(_mandi_payload([])))
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Paddy(Common)")
    assert result["available"] is True
    assert result["state"] == STATE_NO_OFFICIAL_RECORD
    assert result["records"] == []
    assert "no official" in result["state_message"].lower()


def test_records_field_of_wrong_type_is_data_source_error(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse({"records": "oops"}))
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Paddy(Common)")
    assert result["state"] == STATE_DATA_SOURCE_ERROR
    assert result["reason"] == "provider_malformed_response"


def test_retrieved_at_is_agriq_fetch_time_not_the_provider_field(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(_mandi_payload([_record()])))
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Paddy(Common)")
    assert result["retrieved_at"] == result["fetched_at"]
    assert result["retrieved_at"] != "2026-09-27T09:00:00+05:30"
    assert result["provider_updated_at"] == "2026-09-27T09:00:00+05:30"


def test_later_page_failure_keeps_the_records_already_retrieved(monkeypatch):
    full_page = [_record(i) for i in range(agmarknet.PARAM_LIMIT)]

    def _get(url, params=None, **kwargs):
        if params["offset"] == 0:
            return FakeResponse(_mandi_payload(full_page))
        raise requests.ConnectionError("dropped")

    monkeypatch.setattr(requests, "get", _get)
    result = agmarknet.fetch_mandi_prices(api_key="k", commodity="Paddy(Common)")
    assert len(result["records"]) == agmarknet.PARAM_LIMIT


# ---------------------------------------------------------------------------
# Security — credentials never leak into a payload
# ---------------------------------------------------------------------------

def test_api_key_never_appears_in_a_result(monkeypatch):
    secret = "SECRET-KEY-VALUE-123"
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse({"records": "bad"}))
    payload = agmarknet.fetch_mandi_prices(api_key=secret, commodity="Paddy(Common)")
    assert secret not in json.dumps(payload)
    assert "api-key" not in json.dumps(payload)


def test_api_key_never_appears_in_a_success_payload(monkeypatch):
    secret = "SECRET-KEY-VALUE-456"
    monkeypatch.setattr(requests, "get", lambda *a, **k: FakeResponse(_mandi_payload([_record()])))
    payload = agmarknet.fetch_mandi_prices(api_key=secret, commodity="Paddy(Common)")
    assert secret not in json.dumps(payload)
    assert MANDI_CREDENTIAL_MESSAGE not in json.dumps(payload)
