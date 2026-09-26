"""Phase 5 unit tests: risk evaluation protocol, dataset loading, metrics, matching.

The reference events in this file are deterministic TEST INPUTS used only to
exercise the matching and metric maths; they are not shipped as a production
dataset (see ``tests/integration/test_risk_evaluation_flow.py`` for the honest
"no real dataset supplied" behaviour, and ``docs/risk-evaluation.md`` for the
protocol that must be executed with real official records).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from agriq.domain.risk_evaluation import definitions, metrics  # noqa: E402
from agriq.domain.risk_evaluation.dataset import (  # noqa: E402
    ReferenceDataset,
    ReferenceDatasetError,
    ReferenceEvent,
    load_reference_events,
    unavailable,
)
from agriq.domain.risk_evaluation.evaluate import evaluate  # noqa: E402

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)

# Small minima so the documented metric maths can be exercised end to end.
SMALL_MINIMA = {
    "min_events": 2,
    "min_warning_windows": 2,
    "min_calibration_samples": 2,
    "min_lead_time_samples": 2,
}


def _event(risk_type: str, when: datetime, district: str = "Cuttack", **extra) -> dict:
    payload = {
        "risk_type": risk_type,
        "event_at": when.isoformat(),
        "district": district,
        "source": "test-fixture record",
        "source_reference": "TEST-ONLY",
    }
    payload.update(extra)
    return payload


def _warning(
    risk_type: str,
    generated_at: datetime,
    *,
    district: str = "Cuttack",
    status: str = "high",
    probability: float | None = 0.7,
    crop: str | None = None,
    stage: str | None = None,
    assessment_method: str = "rule_based",
    probability_kind: str | None = "rule_score",
) -> dict:
    return {
        "risk_type": risk_type,
        "status": status,
        "probability": probability,
        "generated_at": generated_at.isoformat(),
        "district": district,
        "crop_name": crop,
        "growth_stage": stage,
        "assessment_method": assessment_method,
        "probability_kind": probability_kind,
        "rule_version": "agriq-risk-rules-v1",
    }


# ---------------------------------------------------------------------------
# Protocol definitions (§15, §16)
# ---------------------------------------------------------------------------

def test_every_risk_type_has_a_documented_window():
    for risk_type in (
        "disease_conducive_weather",
        "heavy_rain_flooding",
        "heat_stress",
        "water_stress",
        "market_volatility",
    ):
        window = definitions.window_for(risk_type)
        assert window is not None, f"no evaluation window documented for {risk_type}"
        assert window["false_alert_window_hours"] > 0
        assert window["lead_window_hours"] >= 0
        assert window["warning_statuses"], "a risk type must define its required warning band"


def test_false_alert_and_missed_event_are_defined_in_words():
    assert "FALSE ALERT" in definitions.__doc__
    assert "MISSED EVENT" in definitions.__doc__
    for name in (
        "precision",
        "recall",
        "f1",
        "false_alert_rate",
        "missed_event_rate",
        "brier_score",
        "reliability",
        "warning_lead_time_hours",
    ):
        assert definitions.METRIC_DEFINITIONS[name].strip()
    assert all(value > 0 for value in definitions.SUFFICIENCY.values())


# ---------------------------------------------------------------------------
# Metric maths (§14, §17)
# ---------------------------------------------------------------------------

def test_precision_and_recall_refuse_to_report_below_minimum():
    result = metrics.precision(1, 1, min_warning_windows=10)
    assert result["value"] is None and result["status"] == "insufficient_data"
    assert result["reason"] and result["observed"] == 2
    recall = metrics.recall(1, 0, min_events=10)
    assert recall["value"] is None and recall["status"] == "insufficient_data"
    f1 = metrics.f1_score(result, recall)
    assert f1["value"] is None and f1["status"] == "insufficient_data"


def test_precision_recall_f1_and_rates_maths():
    precision = metrics.precision(3, 1, min_warning_windows=2)
    recall = metrics.recall(3, 1, min_events=2)
    assert precision["value"] == 0.75
    assert recall["value"] == 0.75
    assert metrics.f1_score(precision, recall)["value"] == 0.75
    assert metrics.false_alert_rate(3, 1, min_warning_windows=2)["value"] == 0.25
    assert metrics.missed_event_rate(3, 1, min_events=2)["value"] == 0.25


def test_brier_score_is_the_mean_squared_error():
    pairs = [(0.9, True), (0.1, False)]
    result = metrics.brier_score(pairs, min_samples=2)
    assert result["status"] == "ok"
    assert result["value"] == 0.01


def test_reliability_curve_reports_bins_and_gap():
    pairs = [(0.9, True), (0.9, False), (0.1, False), (0.1, False)]
    result = metrics.reliability_curve(pairs, min_samples=2, bins=4)
    assert result["status"] == "ok"
    assert result["denominators"]["samples"] == 4
    # [0, 0.25): observed 0.0 vs mean 0.1; [0.75, 1]: observed 0.5 vs mean 0.9.
    assert result["max_gap"] == pytest.approx(0.4, abs=1e-6)
    empty_bins = [bin_ for bin_ in result["curve"] if bin_["count"] == 0]
    assert len(empty_bins) == 2  # never filled with a fabricated frequency
    assert all(bin_["observed_frequency"] is None for bin_ in empty_bins)


def test_lead_time_stats_ignore_negative_leads():
    result = metrics.lead_time_stats([24.0, 12.0, -3.0], min_samples=2)
    assert result["status"] == "ok"
    assert result["mean_hours"] == 18.0 and result["median_hours"] == 18.0
    assert result["min_hours"] == 12.0 and result["max_hours"] == 24.0
    assert result["denominators"]["matched_events"] == 2


def test_lead_time_stats_insufficient_without_matches():
    assert metrics.lead_time_stats([], min_samples=5)["status"] == "insufficient_data"


# ---------------------------------------------------------------------------
# Dataset loading (§8, §18)
# ---------------------------------------------------------------------------

def _write_dataset(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "reference_events.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _valid_payload(events: list[dict] | None = None) -> dict:
    return {
        "dataset": {
            "name": "Test reference events",
            "provider": "Test provider",
            "url": "https://example.invalid/records",
            "collection_period": "2026-01-01 to 2026-05-31",
            "geographic_coverage": "Odisha test districts",
            "license": "test-only",
            "retrieved_at": NOW.isoformat(),
        },
        "events": events or [_event("heat_stress", NOW - timedelta(days=20))],
    }


def test_dataset_loads_with_full_provenance(tmp_path):
    dataset = load_reference_events(_write_dataset(tmp_path, _valid_payload()))
    assert dataset.usable is True
    assert dataset.missing_provenance == []
    assert dataset.events[0].risk_type == "heat_stress"
    assert dataset.provenance["provider"] == "Test provider"


def test_dataset_without_required_provenance_is_not_usable(tmp_path):
    payload = _valid_payload()
    payload["dataset"].pop("url")
    dataset = load_reference_events(_write_dataset(tmp_path, payload))
    assert dataset.usable is False
    assert "url" in dataset.missing_provenance


def test_dataset_rejects_unknown_risk_type(tmp_path):
    payload = _valid_payload([{**_event("heat_stress", NOW), "risk_type": "locust_swarm"}])
    with pytest.raises(ReferenceDatasetError):
        load_reference_events(_write_dataset(tmp_path, payload))


def test_dataset_requires_a_source_and_district(tmp_path):
    payload = _valid_payload([{**_event("heat_stress", NOW), "source": ""}])
    with pytest.raises(ReferenceDatasetError):
        load_reference_events(_write_dataset(tmp_path, payload))
    payload = _valid_payload([{**_event("heat_stress", NOW), "district": ""}])
    with pytest.raises(ReferenceDatasetError):
        load_reference_events(_write_dataset(tmp_path, payload))


def test_dataset_rejects_naive_timestamps(tmp_path):
    payload = _valid_payload([{**_event("heat_stress", NOW), "event_at": "2026-05-12T00:00:00"}])
    with pytest.raises(ReferenceDatasetError):
        load_reference_events(_write_dataset(tmp_path, payload))


def test_missing_dataset_file_is_an_error(tmp_path):
    with pytest.raises(ReferenceDatasetError):
        load_reference_events(tmp_path / "absent.json")


# ---------------------------------------------------------------------------
# Matching + report (§13, §14, §16, §17)
# ---------------------------------------------------------------------------

def _scenario() -> tuple[list[dict], ReferenceDataset]:
    """Documented scenario: 2 events, 8 qualifying warnings (1 pending, 5 false)."""
    warnings = [
        # W1 — heavy-rain warning 24 h before the rain event (true positive).
        _warning("heavy_rain_flooding", NOW - timedelta(days=23), probability=0.80, crop="rice", stage="vegetative"),
        # W2 — heavy-rain warning in April; no event inside its window (false alert).
        _warning("heavy_rain_flooding", datetime(2026, 4, 1, tzinfo=timezone.utc), probability=0.70, crop="rice"),
        # W3 — heat warning 12 h before the heat event (true positive).
        _warning("heat_stress", NOW - timedelta(days=20, hours=12), probability=0.70, crop="rice", stage="flowering"),
        # W4 — same heat warning but recorded for tomato; the event is rice (crop conflict).
        _warning(
            "heat_stress", NOW - timedelta(days=20, hours=12), probability=0.65, crop="tomato", stage="flowering"
        ),
        # W5 — water-stress warning with no matching event.
        _warning("water_stress", NOW - timedelta(days=12), probability=0.90),
        # W6 — water-stress warning whose window is still open (pending, excluded).
        _warning("water_stress", NOW - timedelta(days=1), probability=0.70),
        # W7 — market warning with no matching event.
        _warning("market_volatility", NOW - timedelta(days=2), probability=0.50, status="elevated"),
        # W8 — heat warning for a different district than the event.
        _warning(
            "heat_stress", NOW - timedelta(days=20, hours=12), district="Puri", probability=0.70, crop="rice"
        ),
        # W9 — monitor band: informational, not a warning, still a calibration point.
        _warning("disease_conducive_weather", NOW - timedelta(days=7), status="monitor", probability=0.30),
    ]
    dataset = ReferenceDataset(provenance={"name": "scenario", "provider": "test"})
    dataset.events = [
        ReferenceEvent(
            risk_type="heavy_rain_flooding",
            event_at=NOW - timedelta(days=22),
            district="Cuttack",
            source="test-fixture record",
            crop="rice",
            growth_stage="vegetative",
        ),
        ReferenceEvent(
            risk_type="heat_stress",
            event_at=NOW - timedelta(days=20),
            district="Cuttack",
            source="test-fixture record",
            crop="rice",
            growth_stage="flowering",
        ),
    ]
    return warnings, dataset


def test_report_matches_warnings_to_events_and_counts_pending():
    warnings, dataset = _scenario()
    report = evaluate(warnings, dataset, now=NOW, sufficiency=SMALL_MINIMA)
    counts = report["overall"]["counts"]

    assert counts["warnings_issued"] == 8          # monitor band is not a warning
    assert counts["warnings_pending"] == 1         # window still open
    assert counts["warnings_falsifiable"] == 7
    assert counts["warnings_confirmed"] == 2       # W1 + W3
    assert counts["warnings_unconfirmed"] == 5
    assert counts["reference_events"] == 2
    assert counts["events_warned"] == 2
    assert counts["events_missed"] == 0
    assert counts["calibration_pairs"] == 8        # pending window excluded


def test_report_metric_values():
    warnings, dataset = _scenario()
    result = evaluate(warnings, dataset, now=NOW, sufficiency=SMALL_MINIMA)["overall"]["metrics"]

    assert result["precision"]["value"] == round(2 / 7, 4)
    assert result["recall"]["value"] == 1.0
    assert result["f1"]["value"] == round(2 * (2 / 7) * 1.0 / ((2 / 7) + 1.0), 4)
    assert result["false_alert_rate"]["value"] == round(5 / 7, 4)
    assert result["missed_event_rate"]["value"] == 0.0
    assert result["brier_score"]["value"] == 0.3353


def test_warning_lead_time_is_measured_per_event():
    warnings, dataset = _scenario()
    report = evaluate(warnings, dataset, now=NOW, sufficiency=SMALL_MINIMA)
    lead = report["overall"]["metrics"]["warning_lead_time_hours"]

    assert lead["status"] == "ok"
    assert lead["mean_hours"] == 18.0 and lead["median_hours"] == 18.0
    buckets = {entry["bucket"]: entry["count"] for entry in lead["distribution"]}
    assert buckets["12-24h"] == 1 and buckets["24-48h"] == 1

    outcomes = {row["risk_type"]: row for row in report["overall"]["event_outcomes"]}
    rain = outcomes["heavy_rain_flooding"]
    assert rain["warned"] is True
    assert rain["warning_lead_time_hours"] == 24.0
    assert rain["event_time"] and rain["first_valid_warning_time"] and rain["event_source"]


def test_default_minima_report_insufficient_data_instead_of_numbers():
    warnings, dataset = _scenario()
    report = evaluate(warnings, dataset, now=NOW)  # documented production minima
    assert report["status"] == "insufficient_data"
    assert report["overall"]["metrics"]["precision"]["value"] is None
    assert report["reason"] == "below_documented_sample_minimum"
    assert all(value is None for value in (
        report["overall"]["metrics"]["precision"]["value"],
        report["overall"]["metrics"]["recall"]["value"],
    ))


def test_report_groups_by_crop_stage_and_district():
    warnings, dataset = _scenario()
    report = evaluate(warnings, dataset, now=NOW, sufficiency=SMALL_MINIMA)
    subgroups = report["subgroups"]

    assert {"rice", "tomato"} <= set(subgroups["by_crop"]["groups"])
    assert {"cuttack", "puri"} <= set(subgroups["by_district"]["groups"])
    assert {"vegetative", "flowering"} <= set(subgroups["by_stage"]["groups"])

    rice = subgroups["by_crop"]["groups"]["rice"]["counts"]
    assert rice["warnings_confirmed"] == 2 and rice["events_warned"] == 2
    tomato = subgroups["by_crop"]["groups"]["tomato"]["counts"]
    assert tomato["warnings_confirmed"] == 0 and tomato["warnings_unconfirmed"] == 1
    assert rice["reference_events"] == 2

    # Records without the dimension are reported, never silently attributed.
    assert subgroups["by_crop"]["unattributed"]["warnings_without_dimension"] == 4
    assert subgroups["by_crop"]["unattributed"]["events_without_dimension"] == 0


def test_report_without_reference_events_is_insufficient_and_says_why():
    warnings, _ = _scenario()
    report = evaluate(warnings, unavailable("reference_events_unavailable"), now=NOW, sufficiency=SMALL_MINIMA)
    assert report["status"] == "insufficient_data"
    assert report["reason"] == "no_reference_events_in_scope"
    assert report["overall"]["counts"]["reference_events"] == 0
    metrics_without_events = report["overall"]["metrics"]
    # Without events, "no warning was followed by an event" is unverifiable, so
    # precision must NOT be published as 0 (that would manufacture a failure).
    for name in ("precision", "recall", "f1", "false_alert_rate", "missed_event_rate", "brier_score"):
        assert metrics_without_events[name]["status"] == "insufficient_data"
        assert metrics_without_events[name]["value"] is None
    assert all(note for note in report["limitations"])
    assert any("No reference-event dataset" in note for note in report["limitations"])


def test_calibration_status_is_not_validated_for_rule_scores():
    warnings, dataset = _scenario()
    report = evaluate(warnings, dataset, now=NOW, sufficiency=SMALL_MINIMA)
    assert report["calibration_status"] == "not_validated"
    assert any("rule scores, not calibrated probabilities" in note for note in report["limitations"])


def test_calibration_status_validated_only_for_calibrated_probabilities():
    warnings, dataset = _scenario()
    for warning in warnings:
        if warning["probability"] is not None:
            warning["assessment_method"] = "ml"
            warning["probability_kind"] = "calibrated_probability"
    report = evaluate(warnings, dataset, now=NOW, sufficiency=SMALL_MINIMA)
    assert report["calibration_status"] == "validated"


def test_district_less_warnings_are_counted_not_credited():
    """A warning with no district cannot be tied to a district-level event."""
    warnings, dataset = _scenario()
    warnings.append(
        _warning(
            "heavy_rain_flooding", NOW - timedelta(days=23), district=None,
            probability=0.9, crop="rice",
        )
    )
    report = evaluate(warnings, dataset, now=NOW, sufficiency=SMALL_MINIMA)
    counts = report["overall"]["counts"]
    assert counts["warnings_without_district"] == 1
    assert counts["warnings_falsifiable"] == 7      # the district-less one is excluded
    assert counts["warnings_confirmed"] == 2        # and never credited as a true positive


def test_undated_assessments_are_skipped_not_guessed():
    warnings, dataset = _scenario()
    warnings.append({"risk_type": "heat_stress", "status": "high", "probability": 0.9, "generated_at": None})
    report = evaluate(warnings, dataset, now=NOW, sufficiency=SMALL_MINIMA)
    assert report["overall"]["counts"]["warnings_issued"] == 8


def test_protocol_version_is_reported():
    warnings, dataset = _scenario()
    report = evaluate(warnings, dataset, now=NOW)
    assert report["protocol_version"] == definitions.PROTOCOL_VERSION
    assert report["event_windows"] and report["definitions"]
