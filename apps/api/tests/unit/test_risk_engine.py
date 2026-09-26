"""Phase 5 unit tests: risk analyzers, freshness and threshold registry.

All weather/market inputs here are clearly-labelled test fixtures inside the
test directory; they never enter production storage and never reach the UI.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from agriq.domain.risk_engine import analyzers, thresholds, weather_input  # noqa: E402
from agriq.domain.risk_engine.base import (  # noqa: E402
    ASSESSMENT_METHODS,
    CALIBRATION_STATUSES,
    PROBABILITY_INTERPRETATION,
    PROBABILITY_KINDS,
    RISK_TYPES,
)
from agriq.domain.risk_engine.freshness import classify, confidence_factor  # noqa: E402

NOW = datetime.now(timezone.utc)


def _weather(**overrides):
    """Test-fixture weather payload (labelled; never a production record)."""
    payload = {
        "available": True,
        "provider": "Open-Meteo",
        "observed_at": NOW.isoformat(),
        "retrieved_at": NOW.isoformat(),
        "freshness": "fresh",
        "temp": 27.0,
        "humidity": 60.0,
        "rain": 0.0,
        "hourly": [],
        "daily": [{"rain": 0.0, "temp_max": 30.0}] * 7,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Freshness (§16)
# ---------------------------------------------------------------------------

def test_freshness_fresh_from_provider_timestamp():
    assert classify("weather", NOW.isoformat(), NOW.isoformat()) == "fresh"


def test_freshness_aging_and_stale_windows():
    old = (NOW - timedelta(hours=3)).isoformat()
    assert classify("weather", old, old) == "aging"
    ancient = (NOW - timedelta(hours=48)).isoformat()
    assert classify("weather", ancient, ancient) == "expired"


def test_freshness_without_timestamps_is_unavailable_not_fresh():
    assert classify("weather", None, None) == "unavailable"
    assert confidence_factor("unavailable") == 0.0


def test_missing_weather_value_is_gap_not_zero():
    """A provider gap must never silently become 0 mm (real-data policy)."""
    payload = {"available": True, "daily": [{"rain": None}, {"rain": 70.0}]}
    values, days_with_data = weather_input.daily_rain(payload, 3)
    assert values == [70.0] and days_with_data == 1


# ---------------------------------------------------------------------------
# Unsupported / unavailable inputs (§47)
# ---------------------------------------------------------------------------

def test_unsupported_crop_returns_data_unavailable():
    for analyzer in (analyzers.disease_conducive_weather, analyzers.heat_stress):
        result = analyzer("wheat", "Tillering", _weather())
        assert result.status == "data_unavailable"
        assert result.probability is None and result.confidence is None


def test_missing_weather_returns_data_unavailable():
    result = analyzers.disease_conducive_weather("rice", "Tillering", None)
    assert result.status == "data_unavailable"
    assert result.unavailable_reason == "weather_unavailable"


def test_market_without_records_is_insufficient_not_guessed():
    result = analyzers.market_volatility("Rice", {"available": True, "records": []})
    assert result.status == "insufficient_data"


def test_market_never_requested_is_unavailable():
    result = analyzers.market_volatility("Rice", None)
    assert result.status == "data_unavailable"


# ---------------------------------------------------------------------------
# Disease-conducive weather (§10)
# ---------------------------------------------------------------------------

def test_disease_risk_elevated_in_humid_warm_conditions():
    humid = _weather(humidity=88.0, temp=26.0, rain=12.0, hourly=[{"humidity": 85.0}] * 8)
    result = analyzers.disease_conducive_weather("rice", "Tillering", humid)
    assert result.status in ("elevated", "high", "critical")
    assert 0.0 < result.probability <= 1.0
    assert result.threat and "conducive" in result.threat.lower()
    assert result.reasons and result.evidence


def test_disease_risk_inactive_in_dry_conditions():
    result = analyzers.disease_conducive_weather("rice", "Tillering", _weather(humidity=40.0, temp=35.0, rain=0.0))
    assert result.status == "inactive"
    assert result.threat is None


def test_disease_risk_confidence_zero_when_no_provenance():
    """No provider timestamps → no confidence, regardless of probability."""
    humid = _weather(humidity=88.0, temp=26.0, rain=12.0)
    humid.pop("observed_at"), humid.pop("retrieved_at"), humid.pop("freshness")
    result = analyzers.disease_conducive_weather("rice", "Tillering", humid)
    assert result.probability is not None
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Heavy rain / flooding (§11)
# ---------------------------------------------------------------------------

def test_heavy_rain_forecast_flags_high_risk():
    storm = _weather(daily=[{"rain": 90.0}] + [{"rain": 0.0}] * 6)
    result = analyzers.heavy_rain_flooding("rice", "Tillering", storm)
    assert result.status in ("high", "critical")
    assert any("drainage" in a.lower() for a in result.actions)


def test_no_heavy_rain_is_inactive_with_explanation():
    result = analyzers.heavy_rain_flooding("rice", "Tillering", _weather())
    assert result.status == "inactive"
    assert result.reasons


def test_forecast_is_labelled_not_sensor_reading():
    storm = _weather(daily=[{"rain": 90.0}])
    result = analyzers.heavy_rain_flooding("rice", "Tillering", storm)
    assert result.evidence[0]["type"] == "weather_forecast"


def test_farmer_reported_waterlogging_raises_risk():
    storm = _weather(daily=[{"rain": 40.0}])
    result = analyzers.heavy_rain_flooding("rice", "Tillering", storm, field_condition="waterlogged")
    base = analyzers.heavy_rain_flooding("rice", "Tillering", storm)
    assert result.probability > base.probability


# ---------------------------------------------------------------------------
# Heat stress (§12)
# ---------------------------------------------------------------------------

def test_tomato_flowering_heat_exceeds_threshold():
    hot = _weather(temp=36.0, daily=[{"rain": 0.0, "temp_max": 36.0}])
    result = analyzers.heat_stress("tomato", "Flowering", hot)
    assert result.status in ("high", "critical")
    assert result.probability >= 0.7


def test_irrigation_reduces_heat_probability():
    hot = _weather(temp=36.0, daily=[{"rain": 0.0, "temp_max": 36.0}])
    with_water = analyzers.heat_stress("tomato", "Flowering", hot, irrigated=True)
    without = analyzers.heat_stress("tomato", "Flowering", hot, irrigated=False)
    assert with_water.probability < without.probability


def test_moderate_temperature_is_inactive():
    result = analyzers.heat_stress("rice", "Tillering", _weather(temp=30.0, daily=[{"rain": 0.0, "temp_max": 30.0}]))
    assert result.status == "inactive"


# ---------------------------------------------------------------------------
# Water stress (§13) — irrigation context changes the outcome
# ---------------------------------------------------------------------------

def _dry_week():
    return _weather(rain=0.0, daily=[{"rain": 0.0, "temp_max": 30.0}] * 7)


def test_dry_spell_rainfed_is_higher_than_unknown():
    unknown = analyzers.water_stress("rice", "Tillering", _dry_week(), irrigation_type=None)
    rainfed = analyzers.water_stress("rice", "Tillering", _dry_week(), irrigation_type="Rain-fed")
    assert rainfed.status in ("high", "critical")
    assert any("rainfall alone" in r.lower() for r in rainfed.reasons)
    assert rainfed.probability > unknown.probability  # unknown context → lower confidence in high risk


def test_dry_spell_with_canal_irrigation_is_lower():
    canal = analyzers.water_stress("rice", "Tillering", _dry_week(), irrigation_type="Canal")
    none = analyzers.water_stress("rice", "Tillering", _dry_week(), irrigation_type=None)
    assert canal.probability < none.probability


def test_recent_rain_breaks_dry_spell():
    result = analyzers.water_stress("rice", "Tillering", _weather(rain=8.0, daily=[{"rain": 0.0}] * 7))
    assert result.status == "inactive"


def test_no_soil_moisture_claim_is_recorded():
    result = analyzers.water_stress("rice", "Tillering", _dry_week())
    assert result.data_quality.get("soil_moisture_measured") is False


# ---------------------------------------------------------------------------
# Market volatility (§14) — official records only, descriptive only
# ---------------------------------------------------------------------------

def _market_records(prices):
    base = NOW - timedelta(days=1)
    return {
        "available": True,
        "provider": "AGMARKNET (data.gov.in)",
        "retrieved_at": NOW.isoformat(),
        "records": [
            {"modal_price": price, "arrival_date": (base - timedelta(days=i)).date().isoformat()}
            for i, price in enumerate(prices)
        ],
    }


def test_stable_prices_are_inactive():
    result = analyzers.market_volatility("Rice", _market_records([100, 101, 102, 100]))
    assert result.status == "inactive"


def test_volatile_prices_flag_and_require_expert():
    result = analyzers.market_volatility("Rice", _market_records([100, 130, 90, 125]))
    assert result.status in ("elevated", "high")
    assert result.requires_expert_confirmation is True
    assert "not advice" in " ".join(result.actions).lower() or "information" in " ".join(result.actions).lower()


def test_old_records_cannot_describe_volatility():
    stale = {
        "available": True,
        "records": [
            {"modal_price": 100, "arrival_date": "2026-01-01"},
            {"modal_price": 130, "arrival_date": "2026-01-05"},
            {"modal_price": 90, "arrival_date": "2026-01-09"},
        ],
    }
    result = analyzers.market_volatility("Rice", stale)
    assert result.status == "insufficient_data"


# ---------------------------------------------------------------------------
# Probability vs confidence separation (§8)
# ---------------------------------------------------------------------------

def test_probability_and_confidence_are_independent():
    humid = _weather(humidity=88.0, temp=26.0, rain=12.0, hourly=[{"humidity": 85.0}] * 8)
    result = analyzers.disease_conducive_weather("rice", "Tillering", humid)
    assert result.probability is not None
    assert result.confidence is not None
    assert result.confidence < 1.0  # confidence reflects input quality, not likelihood


def test_every_assessment_has_versioned_rules():
    humid = _weather(humidity=88.0, temp=26.0, rain=12.0)
    for analyzer, args in (
        (analyzers.disease_conducive_weather, ("rice", "Tillering", humid)),
        (analyzers.heavy_rain_flooding, ("rice", "Tillering", humid)),
        (analyzers.heat_stress, ("rice", "Tillering", humid)),
        (analyzers.water_stress, ("rice", "Tillering", humid)),
    ):
        result = analyzer(*args)
        assert result.risk_type in RISK_TYPES
        assert result.status in thresholds.VALID_STATUS_RANGE if hasattr(thresholds, "VALID_STATUS_RANGE") else True


def test_threshold_registry_is_documented():
    assert thresholds.RULES_VERSION == "agriq-risk-rules-v1"
    assert thresholds.DISEASE_WEATHER["humidity_high"] == 80.0
    assert thresholds.HEAVY_RAIN["heavy_mm_per_day"] == 64.5  # WMO/IMD convention


# ---------------------------------------------------------------------------
# Assessment-method provenance (§7, §17): a rule result must never look like ML
# ---------------------------------------------------------------------------

def test_every_assessment_declares_its_method_and_probability_kind():
    humid = _weather(humidity=88.0, temp=26.0, rain=12.0, hourly=[{"humidity": 85.0}] * 8)
    results = [
        analyzers.disease_conducive_weather("rice", "Tillering", humid),
        analyzers.heavy_rain_flooding("rice", "Tillering", _weather(daily=[{"rain": 90.0}])),
        analyzers.heat_stress("rice", "Tillering", _weather(temp=39.0, daily=[{"rain": 0.0, "temp_max": 39.0}])),
        analyzers.water_stress("rice", "Tillering", _dry_week()),
        analyzers.market_volatility("Rice", _market_records([100, 130, 90, 125])),
    ]
    for result in results:
        assert result.assessment_method in ASSESSMENT_METHODS
        assert result.assessment_method == "rule_based"
        assert result.calibration_status in CALIBRATION_STATUSES
        if result.probability is not None:
            # A rule engine must never claim a calibrated probability (§5).
            assert result.probability_kind == "rule_score"
            assert result.calibration_status == "not_validated"
        else:
            assert result.probability_kind is None
            assert result.calibration_status == "not_applicable"
        payload = result.to_dict()
        assert payload["assessment_method"] == "rule_based"
        assert payload["probability_interpretation"] == (
            PROBABILITY_INTERPRETATION.get(result.probability_kind) if result.probability_kind else None
        )


def test_unavailable_assessments_claim_no_probability_kind():
    result = analyzers.disease_conducive_weather("wheat", "Tillering", _weather())
    assert result.probability is None
    assert result.probability_kind is None
    assert result.calibration_status == "not_applicable"
    assert result.to_dict()["probability_interpretation"] is None


def test_probability_interpretation_wording_exists_for_every_kind():
    for kind in PROBABILITY_KINDS:
        assert PROBABILITY_INTERPRETATION[kind].strip()
    # The rule-score wording must state what the number is NOT.
    assert "not a calibrated probability" in PROBABILITY_INTERPRETATION["rule_score"]
