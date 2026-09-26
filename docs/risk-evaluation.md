# Risk Evaluation (Phase 5)

**Status of published metrics: unavailable — `insufficient_data`.**
The evaluation framework described below is implemented and tested, but no
real, provanced reference-event dataset has been executed against it yet, so no
precision, recall, F1, false-alert rate, missed-event rate, calibration figure
or warning lead time is displayed anywhere in AGRIQ AI. Those numbers are not
fabricated; the harness returns the honest marker instead.

## What is implemented

| Module | Role |
| --- | --- |
| `domain/risk_evaluation/definitions.py` | the protocol: event windows, false-alert / missed-event definitions, metric definitions, sample minima |
| `domain/risk_evaluation/dataset.py` | strict loading of operator-supplied REAL reference events with provenance |
| `domain/risk_evaluation/metrics.py` | metric maths; returns `insufficient_data` instead of a number below the documented minimum |
| `domain/risk_evaluation/evaluate.py` | matches issued warnings to documented events; overall + per-crop / per-stage / per-district report |
| `cli/evaluate_risk.py` | operator CLI that runs the protocol over the real database |
| `repositories/risk_repository.py::issued_for_evaluation` | read-only export of every warning ever issued (superseded rows included) |

Running it:

```bash
cd apps/api
python -m agriq.cli.evaluate_risk --events /path/to/reference_events.json --out report.json
python -m agriq.cli.evaluate_risk     # prints the current honest insufficient_data state
```

The path may also be set once with `AGRIQ_RISK_REFERENCE_EVENTS`.

## Protocol version

`agriq-risk-evaluation-v1` (`definitions.PROTOCOL_VERSION`). Every report
records the protocol version, the dataset provenance, the event windows and the
metric definitions it applied, so a historical report stays interpretable.

## Event windows (documented per risk type)

| Risk type | False-alert window | Lead window | Required warning band |
| --- | --- | --- | --- |
| `disease_conducive_weather` | 72 h after the warning | 48 h before the event | elevated / high / critical |
| `heavy_rain_flooding` | 72 h | 48 h | elevated / high / critical |
| `heat_stress` | 48 h | 48 h | elevated / high / critical |
| `water_stress` | 120 h | 120 h | elevated / high / critical |
| `market_volatility` | 24 h | 0 h (descriptive, no forecast) | elevated / high / critical |

A `monitor` reading is informational and is **not** counted as a warning;
counting it would inflate recall and hide genuine missed events.

## Metric definitions

* **False alert** — a warning was issued for `(risk_type, district)` and no
  reference event of that risk type was recorded for that district inside the
  risk type's false-alert window.
* **Missed event** — a reference event occurred and no qualifying warning was
  issued for `(risk_type, district)` inside the lead window before it.
* **Precision** = TP / (TP + FP) over falsifiable warning windows.
* **Recall** = TP / (TP + FN) over documented events.
* **F1** — harmonic mean of precision and recall.
* **False-alert rate** = FP / (TP + FP); **Missed-event rate** = FN / (TP + FN).
* **Brier score** — mean squared error between the issued probability and the
  binary outcome, over closed windows.
* **Reliability** — per-bin observed event frequency vs mean issued probability,
  with the maximum bin gap reported.
* **Warning lead time** — `event_time − first_valid_warning_time` per matched
  event, reported as count / mean / median / min / max plus a fixed-bucket
  distribution (`<6h, 6–12h, 12–24h, 24–48h, 48–72h, ≥72h`).
  Negative values (a warning issued after the event) are discarded rather than
  averaged in.

Two honesty rules are enforced in code:

1. Warnings whose window has not closed are **pending**: excluded from precision
   and false-alert rates, never counted as correct.
2. A scope with **no reference events** publishes no outcome figure at all —
   “no warning was followed by an event” is unverifiable when no events were
   recorded, so precision would be a manufactured failure claim.

## Sample minima

Below these, the metric is reported as `insufficient_data` with the observed
counts: `min_events = 10`, `min_warning_windows = 10`,
`min_calibration_samples = 30`, `min_lead_time_samples = 5`.

## Required evaluation dimensions

Every report contains `overall`, `by_crop`, `by_stage` and `by_district`.
Records that lack a dimension are reported under `unattributed` and are excluded
from that group's figures (they remain in the overall figures) — a subgroup
figure never silently claims to represent the whole population.

## Calibration status

`probability` produced by the engine is a **rule score**, not a calibrated
probability, so reports carry `calibration_status: "not_validated"`. Reliable
calibration figures are computed only when a real evaluation sample exists; the
report claims `validated` only when every probability in the sample is a
`calibrated_probability`. Until then, `0.81` must never be described as “81 of
100 comparable cases will experience the event”.

## Reference-event dataset contract

Reference events are supplied by an operator from official sources (IMD /
meteorological department district records, agriculture department reports,
official price series). The file is JSON:

```json
{
  "dataset": {
    "name": "…", "provider": "…", "url": "…",
    "collection_period": "…", "geographic_coverage": "…",
    "license": "…", "units": "…", "retrieved_at": "…"
  },
  "events": [
    {
      "risk_type": "heavy_rain_flooding",
      "event_at": "2026-07-14T00:00:00+00:00",
      "district": "Cuttack",
      "crop": "rice",
      "growth_stage": "vegetative",
      "source": "IMD daily district rainfall",
      "source_reference": "…",
      "detail": "…"
    }
  ]
}
```

Validation is strict and fails loudly: unknown risk types, missing district or
source, and timezone-naive timestamps are rejected. Required provenance is
`name`, `provider`, `url`, `collection_period`, `geographic_coverage`; missing
recommended fields (`license`, `units`, `retrieved_at`) are reported and mark the
dataset unusable for publication.

Nothing in the repository ships a sample or synthetic event dataset. Test
fixtures live in `apps/api/tests/` only and never become production data.

## Evaluation methodology to be executed

1. Collect verified reference events from official sources with dates, districts
   and provenance recorded.
2. Use a temporal split (earlier period for any calibration, later period for
   testing); never random-split, which leaks future information.
3. Run `python -m agriq.cli.evaluate_risk --events …` and keep the JSON report
   as the artefact.
4. Blind agronomist review of sampled assessments for groundedness (does the
   evidence support the status?) and actionability.
5. Report per risk type, per crop, per growth stage and per district, always with
   the dataset provenance, protocol version, rule version and observed counts.

Until steps 1–5 have been completed with real reviewed data, the only correct
public statement is:

> “Risk screening evaluation is in progress; metrics are not yet available.”
