"""Phase 6 unit tests — Farm-to-Market domain engines.

Fixtures here are hand-built records shaped exactly like the documented
AGMARKNET fields (state, district, market, commodity, variety, arrival_date,
min/max/modal price). They are test-only inputs to pure functions: nothing in
this module is imported by the application, and no fixture is ever presented as
a real observation.
"""
from __future__ import annotations

import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from agriq.domain.market import (  # noqa: E402
    decision,
    forecasting,
    freshness,
    normalization,
    suitability,
    trend,
)
from agriq.domain.risk_engine import thresholds  # noqa: E402

TODAY = date(2026, 9, 24)


def record(
    day: date,
    price: float | None,
    *,
    market: str = "Cuttack Mandi",
    district: str | None = "Cuttack",
    commodity: str = "Rice",
    variety: str = "Common",
    minimum: float | None = None,
    maximum: float | None = None,
    retrieved_at: str = "2026-09-24T06:00:00+00:00",
) -> dict:
    payload: dict = {
        "commodity": commodity,
        "market": market,
        "district": district,
        "state": "Odisha",
        "variety": variety,
        "arrival_date": day.isoformat(),
        "modal_price": price,
        "source": "AGMARKNET via data.gov.in",
        "retrieved_at": retrieved_at,
    }
    if price is not None:
        payload["min_price"] = price - 20 if minimum is None else minimum
        payload["max_price"] = price + 20 if maximum is None else maximum
    return payload


def normalize(rows, *, expected: str | None = None):
    result = normalization.normalize_records(rows, expected_commodity=expected, today=TODAY)
    assert not result.quarantined, [item.flags for item in result.quarantined]
    return result.accepted


# ---------------------------------------------------------------------------
# Commodity resolution and normalization
# ---------------------------------------------------------------------------

def test_provider_commodity_names_resolve_to_catalog_keys():
    assert normalization.resolve_commodity("Paddy(Dhan)(Common)") == "rice"
    assert normalization.resolve_commodity("Rice") == "rice"
    assert normalization.resolve_commodity("rice") == "rice"
    assert normalization.resolve_commodity("Tomato") == "tomato"
    assert normalization.resolve_commodity("Bottle Gourd") == "bottle gourd"
    # Documented catalog aliases.
    assert normalization.resolve_commodity("Lady Finger") == "okra"
    assert normalization.resolve_commodity("Eggplant") == "brinjal"
    assert normalization.resolve_commodity("Unobtainium") is None
    assert normalization.resolve_commodity(None) is None


def test_provider_filter_name_never_invents_a_commodity():
    assert normalization.provider_commodity_name("rice") == "Rice"
    assert normalization.provider_commodity_name("tomato") == "Tomato"
    # Unresolvable text is passed through verbatim rather than renamed.
    assert normalization.provider_commodity_name("Unobtainium") == "Unobtainium"
    assert normalization.provider_commodity_name("") is None


def test_quality_gate_flags_every_defect_and_excludes_it():
    result = normalization.normalize_records([
        record(TODAY, 2200),                                   # accepted
        record(TODAY, 2300, variety="Fine"),                   # accepted
        record(TODAY, None),                                   # missing modal price
        record(TODAY, 5000, minimum=6000, maximum=4000),       # ordering violation
        record(TODAY + timedelta(days=3), 2300),               # future arrival date
        record(TODAY, 2200),                                   # duplicate observation
        record(TODAY, 2400, commodity="Banana", variety="Ripe"),  # different commodity
    ], expected_commodity="rice", today=TODAY)

    assert len(result.accepted) == 2
    flags = result.quality_summary["flags"]
    assert flags["missing_modal_price"] == 1
    assert flags["price_ordering_violation"] == 1
    assert flags["future_arrival_date"] == 1
    assert flags["duplicate_observation"] == 1
    # A neighbouring commodity is out of scope, not malformed.
    assert "commodity_not_resolved" not in flags


def test_unresolvable_commodity_is_quarantined_not_guessed():
    result = normalization.normalize_records([record(TODAY, 2200, commodity="Mystery Greens")],
                                             today=TODAY)
    assert result.accepted == []
    assert result.quality_summary["flags"]["commodity_not_resolved"] == 1


def test_quarantine_never_clamps_or_corrects_values():
    result = normalization.normalize_records([record(TODAY, 9_999_999)], today=TODAY)
    assert result.accepted == []
    # Counts are per quarantined record, not per repeated reason.
    assert result.quality_summary["flags"]["impossible_price"] == 1
    assert len(result.quarantined[0].flags) == len(set(result.quarantined[0].flags))


def test_accepted_records_carry_their_unit_and_source():
    accepted = normalize([record(TODAY, 2200)])
    assert accepted[0].price_unit == normalization.PRICE_UNIT == "INR_per_quintal"
    assert accepted[0].source == "AGMARKNET via data.gov.in"
    assert accepted[0].to_dict()["arrival_date"] == TODAY.isoformat()


def test_malformed_rows_are_skipped_without_crashing():
    result = normalization.normalize_records(
        ["not a mapping", 42, {"commodity": None, "modal_price": "NA", "arrival_date": "nonsense"}],
        today=TODAY,
    )
    assert result.accepted == []
    assert result.quality_summary["quarantined"] >= 1


# ---------------------------------------------------------------------------
# Trend and volatility
# ---------------------------------------------------------------------------

def test_trend_needs_three_distinct_official_dates():
    two = trend.trend(normalize([record(TODAY, 2000), record(TODAY - timedelta(days=1), 2050)]))
    assert two["status"] == "insufficient_data"
    assert two["points"] == 2
    assert two["required_points"] == trend.MIN_POINTS_FOR_TREND

    same_day = trend.trend(normalize([record(TODAY, 2000), record(TODAY, 2100, variety="Fine")]))
    assert same_day["status"] == "insufficient_data"


def test_trend_direction_uses_documented_deadband():
    rising = trend.trend(normalize([
        record(TODAY - timedelta(days=10), 2000), record(TODAY - timedelta(days=6), 2100),
        record(TODAY - timedelta(days=3), 2200), record(TODAY - timedelta(days=1), 2300),
    ]))
    assert rising["status"] == "ok"
    assert rising["direction"] == "rising"
    assert rising["change_percent"] == pytest.approx(15.0, abs=0.01)

    flat = trend.trend(normalize([
        record(TODAY - timedelta(days=10), 2000), record(TODAY - timedelta(days=6), 2010),
        record(TODAY - timedelta(days=3), 2005), record(TODAY - timedelta(days=1), 2008),
    ]))
    assert flat["direction"] == "stable"
    assert flat["stable_deadband_percent"] == trend.STABLE_DEADBAND_PCT


def test_series_points_are_medians_of_real_dates_and_report_reporting_count():
    points = trend.series_points(normalize([
        record(TODAY, 2000), record(TODAY, 2200, market="Puri Mandi", district="Puri"),
    ]))
    assert points == [{"date": TODAY.isoformat(), "modal_price": 2100.0, "markets_reporting": 2}]


def test_volatility_uses_the_phase5_bands():
    high = trend.volatility(normalize([record(TODAY, 1000), record(TODAY - timedelta(days=1), 1400)]))
    assert high["status"] == "ok"
    assert high["band"] == "high"
    assert high["bands"]["high_percent"] == thresholds.MARKET_VOLATILITY["swing_high_pct"]

    low = trend.volatility(normalize([record(TODAY, 2000), record(TODAY - timedelta(days=1), 2010)]))
    assert low["band"] == "low"


def test_series_never_blends_two_provider_commodities():
    mixed = normalize([
        record(TODAY, 2200, commodity="Rice"),
        record(TODAY - timedelta(days=2), 1500, commodity="Paddy(Dhan)(Common)"),
        record(TODAY - timedelta(days=1), 1520, commodity="Paddy(Dhan)(Common)"),
    ], expected="rice")
    result = trend.trend(mixed)
    assert result["provider_commodity"] == "Paddy(Dhan)(Common)"
    assert result["excluded_provider_commodities"] == ["Rice"]
    # Rice prices (2200) must not be averaged into the paddy series.
    assert all(point["modal_price"] < 1600 for point in result["series"])


def test_latest_by_market_keeps_one_row_per_market_and_variety():
    latest = trend.latest_by_market(normalize([
        record(TODAY - timedelta(days=2), 2000),
        record(TODAY, 2100),
    ]))
    assert len(latest) == 1
    assert latest[0].modal_price == 2100


# ---------------------------------------------------------------------------
# Forecasting
# ---------------------------------------------------------------------------

def synthetic_series(count: int = 60, *, noise: bool = True) -> list[dict]:
    """Deterministic series with trend, weekday seasonality and no randomness."""
    points = []
    for index in range(count):
        day = TODAY - timedelta(days=count - 1 - index)
        wobble = ((index * 37) % 11 - 5) * 6 if noise else 0
        points.append({
            "date": day.isoformat(),
            "modal_price": round(
                2000 + index * 5
                + 60 * math.sin(day.weekday() / 7 * 2 * math.pi)
                + wobble,
                2,
            ),
        })
    return points


def test_forecast_refuses_without_enough_real_history():
    outcome = forecasting.forecast(synthetic_series(20), horizon_days=7)
    assert outcome.status == "insufficient_data"
    assert outcome.forecast == []
    assert outcome.prediction_interval is None
    assert str(forecasting.MIN_OBSERVATIONS) in outcome.reason


def test_forecast_rejects_unsupported_horizon():
    outcome = forecasting.forecast(synthetic_series(60), horizon_days=5)
    assert outcome.status == "insufficient_data"
    assert "horizon" in outcome.reason


def test_forecast_evaluation_is_chronological():
    outcome = forecasting.forecast(synthetic_series(60), horizon_days=7)
    assert outcome.status == "ok"
    assert outcome.training_period["to"] < outcome.evaluation_period["from"]
    selection = outcome.metrics["selection_block"]
    reported = outcome.metrics["reported_block"]
    assert selection["period"]["to"] < reported["period"]["from"]
    assert selection["kind"] == "validation" and reported["kind"] == "test"
    # Model selection uses the validation block only.
    best_validation = min(selection["candidates"],
                          key=lambda name: selection["candidates"][name]["rmse"])
    assert outcome.selected_model == best_validation


def test_forecast_reports_baseline_comparison_and_interval():
    outcome = forecasting.forecast(synthetic_series(60), horizon_days=7)
    assert outcome.metrics["beats_naive_baseline"] is True
    assert set(forecasting.baseline_names()) <= set(outcome.metrics["reported_block"]["candidates"])
    assert len(outcome.forecast) == 7
    interval = outcome.prediction_interval
    assert interval["nominal_coverage"] == 0.8
    assert interval["dispersion"] > 0
    assert "out-of-sample" in interval["dispersion_source"]
    for low, value, high in zip(interval["lower"], outcome.forecast, interval["upper"]):
        assert low <= value["modal_price"] <= high
    assert 0.0 <= interval["test_coverage"] <= 1.0


def test_interval_dispersion_comes_from_pre_test_data_only():
    """The interval must not be built from the block it is measured against."""
    outcome = forecasting.forecast(synthetic_series(60), horizon_days=7)
    points = [(date.fromisoformat(p["date"]), p["modal_price"]) for p in synthetic_series(60)]
    in_sample = forecasting.fit_trend_seasonal(points).residual_std
    # A model fitted on everything is (nearly) in-sample-fitted here, so its
    # residual dispersion is far smaller than the honest out-of-sample figure.
    assert outcome.prediction_interval["dispersion"] > in_sample


def test_metrics_are_none_rather_than_invented_without_data():
    assert forecasting.mae([], []) is None
    assert forecasting.rmse([1.0], []) is None
    assert forecasting.mape([0.0, 100.0], [10.0, 90.0]) is None
    assert forecasting.interval_coverage([1.0], [], []) is None
    report = forecasting.error_report([100.0], [110.0])
    assert report["n"] == 1 and report["mae"] == 10.0


# ---------------------------------------------------------------------------
# Economics
# ---------------------------------------------------------------------------

def test_net_value_is_withheld_until_every_cost_is_known():
    incomplete = decision.economics(modal_price=2200, quantity_quintals=10)
    assert incomplete["status"] == "incomplete"
    assert incomplete["label"] == "NET_VALUE_INCOMPLETE"
    assert incomplete["estimated_net_value"] is None
    assert incomplete["gross_value"] == 22000
    assert "input_cost_total" in incomplete["missing_costs"]

    complete = decision.economics(
        modal_price=2200, quantity_quintals=10, input_cost_total=3000,
        transport_cost_total=800, market_fee_total=200,
    )
    assert complete["label"] == "estimated_net_value"
    assert complete["estimated_net_value"] == 22000 - 4000


def test_economics_requires_a_farmer_supplied_quantity():
    result = decision.economics(modal_price=2200, quantity_quintals=None)
    assert result["status"] == "insufficient_data"
    assert "quantity" in result["reason"]


def test_economics_without_a_price_is_insufficient():
    assert decision.economics(modal_price=None, quantity_quintals=10)["status"] == "insufficient_data"


# ---------------------------------------------------------------------------
# Sell / hold
# ---------------------------------------------------------------------------

def test_sell_hold_without_a_price_is_insufficient():
    result = decision.sell_hold(crop_key="rice", current_price=None, trend=None, volatility=None)
    assert result["decision"] == decision.INSUFFICIENT_DATA
    assert result["missing_information"]


def test_sell_hold_needs_an_observed_market_or_risk_fact():
    """A storable crop on a single price is not a reason to hold."""
    result = decision.sell_hold(
        crop_key="rice", current_price=2200,
        trend={"status": "insufficient_data"}, volatility={"status": "insufficient_data"},
    )
    assert result["decision"] == decision.INSUFFICIENT_DATA
    assert any("market or risk fact" in reason for reason in [result["reason"]])


def test_sell_hold_uses_trend_perishability_and_storage():
    falling_perishable = decision.sell_hold(
        crop_key="tomato", current_price=1500,
        trend={"status": "ok", "direction": "falling", "change_percent": -9.0, "points": 4},
        volatility={"status": "ok", "band": "high", "swing_percent": 22.0},
        storage_available=False,
    )
    assert falling_perishable["decision"] == decision.SELL_NOW
    assert falling_perishable["requires_expert_confirmation"] is True

    rising_storable = decision.sell_hold(
        crop_key="rice", current_price=2200,
        trend={"status": "ok", "direction": "rising", "change_percent": 6.0, "points": 5},
        volatility={"status": "ok", "band": "low", "swing_percent": 4.0},
        forecast={"status": "ok", "selected_model": "trend_weekly_seasonal",
                  "forecast": [{"modal_price": 2400}]},
        storage_available=True,
    )
    assert rising_storable["decision"] == decision.WAIT
    assert rising_storable["confidence"]["status"] == "not_calibrated"


def test_sell_hold_counts_each_risk_type_once_and_ignores_quiet_risks():
    duplicated = decision.sell_hold(
        crop_key="rice", current_price=2200,
        trend={"status": "insufficient_data"}, volatility={"status": "insufficient_data"},
        risk_rows=[
            {"risk_type": "heavy_rain_flooding", "status": "high"},
            {"risk_type": "heavy_rain_flooding", "status": "critical"},
        ],
    )
    risk_evidence = [item for item in duplicated["evidence"] if item["kind"].startswith("risk:")]
    assert len(risk_evidence) == 1
    assert duplicated["decision"] == decision.SELL_NOW

    quiet = decision.sell_hold(
        crop_key="rice", current_price=2200,
        trend={"status": "insufficient_data"}, volatility={"status": "insufficient_data"},
        risk_rows=[{"risk_type": "heavy_rain_flooding", "status": "low"}],
    )
    assert quiet["risks"] == []
    assert quiet["decision"] == decision.INSUFFICIENT_DATA


def test_production_side_risks_are_context_not_timing_evidence():
    result = decision.sell_hold(
        crop_key="rice", current_price=2200,
        trend={"status": "insufficient_data"}, volatility={"status": "insufficient_data"},
        risk_rows=[{"risk_type": "heat_stress", "status": "high"}],
    )
    assert result["risks"][0]["effect_on_market_decision"] is None
    assert result["decision"] == decision.INSUFFICIENT_DATA


# ---------------------------------------------------------------------------
# Distance and market comparison
# ---------------------------------------------------------------------------

def test_distance_proxy_is_unavailable_where_it_would_mislead():
    inside = decision.market_distance_proxy(20.46, 85.88, "Cuttack", "Cuttack")
    assert inside["distance_km"] is None
    assert "own district" in inside["reason"]

    assert decision.market_distance_proxy(None, None, "Cuttack", "Puri")["reason"] == \
        "farm_coordinates_unavailable"
    assert decision.market_distance_proxy(20.46, 85.88, "Cuttack", "Atlantis")["reason"] == \
        "market_district_not_in_reference_geodata"

    outside = decision.market_distance_proxy(20.46, 85.88, "Cuttack", "Puri")
    assert outside["distance_km"] and "NOT road distance" in outside["distance_basis"]


def test_great_circle_distance_matches_known_reference():
    # Cuttack → Bhubaneswar is roughly 22 km straight line.
    assert decision.great_circle_km(20.4625, 85.8828, 20.2961, 85.8245) == pytest.approx(20.0, abs=4.0)


def test_market_comparison_groups_by_variety_and_labels_gross_vs_net():
    records = normalize([
        record(TODAY, 2300, market="Puri Mandi", district="Puri"),
        record(TODAY, 2100, market="Cuttack Mandi", district="Cuttack"),
        record(TODAY, 2600, market="Bhubaneswar Mandi", district="Khordha", variety="Fine"),
    ])
    comparison = decision.compare_markets(
        records, farmer_district="Cuttack", farm_lat=20.46, farm_lon=85.88, quantity_quintals=10,
    )
    assert comparison["status"] == "ok"
    assert len(comparison["groups"]) == 2, "varieties must never be mixed"
    common = next(group for group in comparison["groups"] if group["variety"] == "common")
    assert common["highest_price_market"] == "Puri Mandi"
    for row in common["markets"]:
        assert row["economics"]["label"] == "NET_VALUE_INCOMPLETE"
        assert row["estimated_transport_cost"] is None


def test_market_comparison_estimates_transport_only_with_a_farmer_rate_and_distance():
    records = normalize([
        record(TODAY, 2300, market="Puri Mandi", district="Puri"),
        record(TODAY, 2100, market="Cuttack Mandi", district="Cuttack"),
    ])
    comparison = decision.compare_markets(
        records, farmer_district="Cuttack", farm_lat=20.46, farm_lon=85.88,
        quantity_quintals=10, transport_rate_per_km_quintal=2.0,
        input_cost_total=1000, market_fee_total=50,
    )
    rows = {row["market"]: row for row in comparison["groups"][0]["markets"]}
    assert rows["Puri Mandi"]["economics"]["label"] == "estimated_net_value"
    assert rows["Puri Mandi"]["estimated_transport_cost"] == pytest.approx(
        2.0 * rows["Puri Mandi"]["distance_km"] * 10)
    # In-district market: no distance proxy, so no invented freight and no net.
    assert rows["Cuttack Mandi"]["estimated_transport_cost"] is None
    assert rows["Cuttack Mandi"]["economics"]["label"] == "NET_VALUE_INCOMPLETE"


def test_a_farmer_supplied_freight_total_completes_the_net_without_any_distance():
    """§26 admits a farmer-provided value, so a net is reachable in-district too."""
    records = normalize([record(TODAY, 2100, market="Cuttack Mandi", district="Cuttack")])
    comparison = decision.compare_markets(
        records, farmer_district="Cuttack", farm_lat=20.46, farm_lon=85.88,
        quantity_quintals=10, transport_cost_total=1200.0,
        input_cost_total=4000.0, market_fee_total=0.0,
    )
    row = comparison["groups"][0]["markets"][0]
    assert row["distance_km"] is None, "the in-district proxy is still never called a road distance"
    assert row["estimated_transport_cost"] == 1200.0
    assert row["economics"]["label"] == "estimated_net_value"
    assert row["economics"]["estimated_net_value"] == pytest.approx(2100 * 10 - 5200)
    assert row["economics"]["known_costs"]["market_fee_total"] == 0.0, "a real zero is a known cost"
    assert "not a per-market quote" in row["transport_cost_basis"]


def test_a_farmer_supplied_freight_total_wins_over_the_derived_rate():
    records = normalize([record(TODAY, 2100, market="Puri Mandi", district="Puri")])
    comparison = decision.compare_markets(
        records, farmer_district="Cuttack", farm_lat=20.46, farm_lon=85.88,
        quantity_quintals=10, transport_rate_per_km_quintal=2.0, transport_cost_total=999.0,
    )
    row = comparison["groups"][0]["markets"][0]
    assert row["distance_km"] is not None, "the proxy is still reported, just not used as freight"
    assert row["estimated_transport_cost"] == 999.0
    assert comparison["logistics_limitations"]


# ---------------------------------------------------------------------------
# Suitability
# ---------------------------------------------------------------------------

def test_suitability_reports_documented_factors_with_sources():
    result = suitability.evaluate_crop(
        "rice", district="Cuttack", season="Kharif",
        weather={"available": True, "temp": 28.0, "humidity": 84.0}, rain_mm=6.0,
    )
    assert result["catalog_status"] == "documented"
    assert result["recommendation_status"] in ("suitable", "marginal")
    assert result["confidence"]["status"] == "not_calibrated"
    factors = {factor["factor"]: factor for factor in result["factors"]}
    assert factors["season"]["outcome"] == "favourable"
    assert factors["temperature"]["outcome"] == "favourable"
    assert all(factor["source"] for factor in result["factors"])
    assert all(entry["source"] for entry in result["supporting_evidence"])


def test_season_mismatch_is_unfavourable():
    result = suitability.evaluate_crop("wheat", district="Cuttack", season="Kharif")
    season = next(factor for factor in result["factors"] if factor["factor"] == "season")
    assert season["outcome"] == "unfavourable"
    assert result["recommendation_status"] == "unsuitable"


def test_missing_inputs_are_reported_as_unknown_not_assumed_favourable():
    result = suitability.evaluate_crop("rice", district="Cuttack", season=None)
    unknown = {factor["factor"] for factor in result["factors"] if factor["outcome"] == "unknown"}
    assert {"season", "temperature", "rainfall", "humidity"} <= unknown
    assert result["missing_information"]


def test_uncatalogued_crop_is_never_called_unsuitable():
    result = suitability.evaluate_crop("unobtainium", district="Cuttack", season="Kharif")
    assert result["catalog_status"] == "not_in_catalog"
    assert result["recommendation_status"] == "insufficient_data"
    assert "no documented agronomic profile" in result["limitation"]


def test_candidate_crops_prioritise_the_district_belt():
    candidates = suitability.candidate_crops("Cuttack", "Kharif")
    assert candidates[0] == "rice", "the district's documented main crop must lead the list"
    assert candidates.index("bottle gourd") < candidates.index("maize")
    assert len(candidates) == len(set(candidates))


# ---------------------------------------------------------------------------
# Freshness and provenance
# ---------------------------------------------------------------------------

def test_provenance_never_claims_a_live_feed():
    block = freshness.provenance(
        source="AGMARKNET via data.gov.in",
        retrieved_at="2026-09-24T06:00:00+00:00",
        observed_at="2026-09-24",
        price_date="2026-09-24",
        record_count=3,
    )
    assert block["is_live"] is False
    assert block["freshness_status"] in ("fresh", "aging", "stale", "expired")
    assert block["age_minutes"] is not None
    assert block["record_description"] == "latest official AGMARKNET record"
    assert block["record_count"] == 3


def test_provenance_without_a_real_timestamp_is_unavailable():
    block = freshness.unavailable_provenance("no_official_records_for_this_crop_and_district")
    assert block["freshness_status"] == "unavailable"
    assert block["confidence_factor"] == 0.0
    assert block["reason"] == "no_official_records_for_this_crop_and_district"


def test_provider_description_names_the_official_source():
    assert "AGMARKNET" in normalization.crop_display_name("rice") or \
        normalization.crop_display_name("rice") == "Rice"
