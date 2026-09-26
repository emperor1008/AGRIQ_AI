# Risk Intelligence Engine (Phase 5)

The Crop Risk Intelligence engine evaluates agricultural risk for a specific
farmer's field by combining verified contextual data. It is a **deterministic
rule engine**: every number shown to a farmer is traceable to documented
thresholds (`agriq-risk-rules-v1`) and real provider data. No ML model is used
in this phase; the architecture allows a validated model to later replace any
individual analyzer.

## Status

**Implemented as described here; evaluation harness implemented, metrics still
`insufficient_data`** (see `docs/risk-evaluation.md`). No accuracy, precision or
recall figures are displayed anywhere because no validated reference-event
dataset has been executed yet — none are fabricated.

## Architecture

```
Shared Farmer Context (single source of truth)
        │  ownership-verified (raises PermissionError on foreign ids)
        ▼
risk_service.analyze_context()
        │
        ├── weather_input.gather()      (Phase 1 weather service + Open-Meteo)
        ├── market_service (optional)   (official AGMARKNET records only)
        ├── latest image screening      (supporting evidence only)
        ▼
5 deterministic analyzers (domain/risk_engine/analyzers.py)
        ▼
append-only persistence (supersede, never overwrite)
        ▼
/api/v1/risk/* (HTTP only; no calculations in routes)
```

Modules:

| Path | Role |
| --- | --- |
| `domain/risk_engine/base.py` | `Assessment` contract, probability/confidence separation |
| `domain/risk_engine/thresholds.py` | versioned threshold registry (`agriq-risk-rules-v1`) |
| `domain/risk_engine/analyzers.py` | the five analyzers (pure functions) |
| `domain/risk_engine/freshness.py` | fresh/aging/stale/expired classification |
| `domain/risk_engine/weather_input.py` | normalises weather payload + evidence blocks |
| `domain/risk_evaluation/` | offline evaluation: protocol, dataset loading, metrics, matcher |
| `services/risk_service.py` | orchestration, persistence, action tracking |
| `repositories/risk_repository.py` | owner-scoped, append-only persistence |
| `api/risk.py` | HTTP routes (auth, ownership, serialisation) |
| `cli/evaluate_risk.py` | operator CLI that runs the evaluation protocol |

## Risk types and methodology

All thresholds live in `domain/risk_engine/thresholds.py`. They are **screening
baselines** from standard agrometeorology conventions (WMO/IMD rainfall bands,
crop heat-sensitivity reference points, fungal-disease pressure windows) —
*not* Odisha-validated agronomy, and never presented as diagnosis.

### 1. Disease-conducive weather (`disease_conducive_weather`)

Signals: RH ≥ 80 %, temperature in the 20–30 °C fungal window, ≥ 10 mm
rain/24 h, sustained high-RH forecast hours. Probability = fraction of
available signals firing (+0.10 at reproductive stages). Output language
always says conditions are *conducive*, never that disease is present.

### 2. Heavy rain / flooding (`heavy_rain_flooding`)

Peak 3-day forecast rainfall against WMO/IMD bands: ≥ 35 mm/d moderate,
≥ 64.5 heavy, ≥ 115 very heavy, ≥ 204.5 extreme. Farmer-reported waterlogged
condition raises probability; reproductive stage adds context. Distinguishes
*forecast rain* from *waterlogging potential*; never claims confirmed flooding.

### 3. Heat stress (`heat_stress`)

Crop/stage-aware screening limits: rice 35 °C (flowering) / 37 °C (vegetative),
tomato 32 / 35 °C. Available irrigation reduces probability (+/− 0.10).

### 4. Water stress (`water_stress`)

Dry-spell length from the 7-day forecast (rain < 5 mm/day does not break the
spell; a wet observation or farmer-reported wet condition does). **Irrigation
context changes the outcome**: canal/bore/well reduces probability, rain-fed
raises it, unknown stays unknown. No soil-moisture sensor exists, so
`soil_moisture_measured: false` is recorded and confidence is capped
accordingly.

### 5. Market volatility (`market_volatility`)

Descriptive statistics over **official AGMARKNET records only** (≥ 3 records
≤ 30 days old): modal-price swing vs median across 8 %/15 % bands. It is
explicitly labelled information, not advice; requires expert confirmation
when the swing is high. Missing/old records → honest
`DATA_UNAVAILABLE`/`INSUFFICIENT_DATA` — never synthetic prices.

## Status model

`inactive` (0–0.24) → `monitor` (0.25–0.44) → `elevated` (0.45–0.64) →
`high` (0.65–0.79) → `critical` (0.80–1.0), plus `data_unavailable` and
`insufficient_data` for honest gaps. The engine is fully capable of returning
"No elevated risk detected" — not every result is a warning.

## Probability vs confidence

- **Probability** — rule-derived likelihood the condition exists/occurs.
- **Confidence** — trust in the assessment quality, from a documented weighted
  formula (`copilot-confidence-v1`): input freshness (0.4) × context
  completeness (0.3) × evidence directness (0.3), as a weighted geometric
  product. Stale inputs reduce confidence; missing provenance yields
  confidence 0. The two numbers are stored, returned and displayed separately.

## Assessment method, probability kind and calibration

Three stored provenance fields make the origin of every number explicit, so a
rule screening can never be read as a validated model probability:

| Field | Values | Meaning today |
| --- | --- | --- |
| `assessment_method` | `rule_based` \| `ml` \| `hybrid` | Always `rule_based` — the five analyzers are deterministic rules |
| `probability_kind` | `rule_score` \| `uncalibrated_ml_probability` \| `calibrated_probability` \| `NULL` | `rule_score` whenever a probability exists; `NULL` when none was produced |
| `calibration_status` | `not_validated` \| `validated` \| `not_applicable` | `not_validated` for every rule score; `not_applicable` when there is no probability |

The API additionally returns `probability_interpretation`, rebuilt from
`probability_kind` (never stored, so the wording cannot drift):

> “rule-derived screening estimate from documented thresholds — not a
> calibrated probability of the event occurring”

A `rule_score` is the fraction of documented screening signals that fired; it
is **not** “an N % chance that disease/flooding/etc. will occur”. Interpreting
it that way would require calibration evidence that does not exist yet. If a
validated model is registered later, `assessment_method` becomes `ml` (or
`hybrid`) and `calibration_status` can only move to `validated` when the
evaluation sample genuinely supports it (`domain/risk_evaluation/evaluate.py`
claims `validated` only when every probability in the sample is a
`calibrated_probability`).

`probability_kind` deliberately has no database column default: an assessment
with no probability stores `NULL` rather than being silently labelled
`rule_score`.

## Freshness

Weather inputs are classified from **real provider timestamps**:
fresh ≤ 1.5 h, aging ≤ 6 h, stale ≤ 36 h, expired beyond, `unavailable` when
no timestamp exists. Freshness multiplies confidence (1.0 / 0.85 / 0.6 / 0.3 /
0) and is displayed to the farmer. Stale data is never silently presented as
current.

## Persistence

`risk_assessments` (migration `0005_phase5_risk`) stores one row per
assessment with `run_group` linking a run. New runs **supersede** the previous
active run (`record_status: superseded`); history is never deleted. A re-run
whose results are unchanged keeps the existing rows (deduplication, no
duplicate warnings). Assessment probability is banded to 0.05 in storage.

## Farmer action tracking

`POST /api/v1/risk/assessments/{id}/action` records the farmer's response via
the existing `farmer_actions` flow: the assessment's primary action is
persisted once as a structured `Recommendation`, and each response
(planned/completed/skipped/needs_help) becomes a `FarmerAction`. Actions are
never auto-completed; outcomes are farmer-entered facts.

## Limitations

- Screening baselines, not locally validated agronomy.
- No ML anywhere in the engine; no fabricated evaluation metrics.
- Probabilities are rule scores, not calibrated probabilities
  (`calibration_status: not_validated`); the wording says so everywhere.
- Risk evaluation runs offline against an operator-supplied real reference
  dataset; until that dataset exists no outcome metric is published.
- Market volatility needs `DATA_GOV_IN_API_KEY` and ≥ 3 recent official records.
- Weather forecast rows come from the Open-Meteo payload; a snapshot cached
  before forecast availability yields honest `insufficient_data` for
  rain/flood risk.
- Supported crops: rice, tomato only. Others → `crop_not_supported`.
