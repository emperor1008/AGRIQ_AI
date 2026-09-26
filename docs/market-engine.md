# Market Engine (Phase 6)

How the Farm-to-Market Optimizer turns official records into statements it is
allowed to make. The governing rule is **NO DATA → NO CLAIM**: every number is
either a stored official record, arithmetic over stored records, or a forecast
the engine actually produced with a documented evaluation; everything else is an
explicit unavailable/insufficient state.

## Module map

| Module | Owns |
| --- | --- |
| `domain/market/normalization.py` | one comparable record shape, commodity resolution, data-quality quarantine |
| `domain/market/freshness.py` | freshness classification + provenance block (delegates to `domain/risk_engine/freshness.py`) |
| `domain/market/trend.py` | scoping, `latest_by_market`, `trend`, `volatility`, `series_points` |
| `domain/market/forecasting.py` | chronological evaluation, candidate models, metrics, prediction interval |
| `domain/market/suitability.py` | agronomic suitability factors per crop/district/season |
| `domain/market/decision.py` | economics, sell/hold, market comparison, distance proxy |
| `services/market_intelligence.py` | orchestration: farmer context → provider + stored history → engines → payload |

Routes (`api/market_intel.py`) only parse, authorise, call the service and
serialise. No market arithmetic lives in a route, and no arithmetic lives in the
browser.

## 1. Normalization and the quality gate

* **Canonical unit** is `INR_per_quintal`, the unit AGMARKNET publishes. A record
  whose unit cannot be established is quarantined, never converted.
* **Commodity resolution** goes through the crop catalog, so the provider's own
  spelling (`Paddy(Dhan)(Common)`) resolves to the same crop as the farmer's
  (`Rice`). An unresolvable commodity is quarantined rather than guessed at.
* **Varieties are never mixed.** Aggregation groups by `(commodity, variety)`.
* **Quality flags** exclude a record from every calculation and are reported back:
  `missing_modal_price`, `impossible_price`, `price_ordering_violation`
  (max < modal < min violated), `invalid_arrival_date`, future-dated rows, and
  duplicates. Suspicious data is never silently "fixed".
* Plausibility ceilings (`MIN_PLAUSIBLE_PRICE`, `MAX_PLAUSIBLE_PRICE`) only flag
  values for quarantine — nothing is clamped or corrected.

## 2. Trend and volatility

* `scoped()` keeps one provider commodity at a time: paddy and rice rows are
  never blended into one series.
* `series_points()` emits one point per observation date as the **median** modal
  price across markets reporting that date, and states `markets_reporting` — so
  an aggregated point is never presented as a single market's price.
* `trend()` reports `insufficient_data` below its minimum observation count;
  `volatility()` reports the band (`low`/`medium`/`high`) from the percentage
  swing around the median.

## 3. Forecasting — chronological, baseline-compared

Evaluation is strictly chronological: the oldest observations train, the next
block validates (used for **model selection**), the newest block is the reported
test block. Nothing from the future feeds a feature or a selection decision.
The test block is never used to build the prediction interval either: the
interval dispersion comes from the out-of-sample (validation/test) residuals.

| Parameter | Value |
| --- | --- |
| Minimum observations before publishing | 21 (`MIN_OBSERVATIONS`) |
| Minimum training observations | 10 (`MIN_TRAIN_OBSERVATIONS`) |
| Supported horizons | 7 and 14 days (`SUPPORTED_HORIZONS`) |
| Model version | `agriq-price-forecast-v1` |
| Candidates | naive (last value), seasonal naive (lag 7), moving average (7), fitted linear-trend + weekday-seasonal model (`TrendSeasonalModel`, pure Python) |

Every published forecast carries `training_period`, `validation_period`,
`evaluation_period`, the selected model, the candidate metrics (`mae`, `rmse`,
`smape_percent`, `mape_percent` — with an explicit reason when undefined),
separately for the selection (validation) and reported (test) blocks, plus
`metrics.beats_naive_baseline`. The prediction interval is a documented normal approximation from
residual dispersion grown with √horizon; `interval_method` states that it is
**not** a statistically calibrated interval. Below the minimum counts the
response is `insufficient_data` with the counts required — never a number, and
the refusal names the location scope it used.

## 4. Agronomic suitability

Each factor is a rule over curated reference data, so every statement traces to
its source: temperature window (`ideal_temp`), humidity sensitivity, rainfall
sensitivity, season, soil, the district's documented production belt, and live
verified weather where available. Outcomes are per-factor
`favourable / caution / unfavourable / unknown`; a factor with a missing input is
`unknown`, never assumed fine. The overall `recommendation_status` is
`suitable / marginal / unsuitable / insufficient_data` with `reasons` and
`supporting_evidence`. This is the project's curated agronomic reference, not a
locally calibrated yield model — no yield is ever predicted.

## 5. Economics — gross is not net

* `gross_value = modal_price × quantity_quintals`, computed only when the farmer
  supplies a quantity (AGRIQ does not estimate yield).
* `estimated_net_value` is published **only** when every component
  (`input_cost_total`, `transport_cost_total`, `market_fee_total`) is known.
  Otherwise `status="incomplete"`, `label="NET_VALUE_INCOMPLETE"`,
  `estimated_net_value=null`, and `missing_costs` names exactly what is absent.
  A gross value is never relabelled as profit.
* Cost provenance states that AGRIQ has no verified freight or input-cost source,
  so those figures can only come from the farmer.
* Transport cost has exactly two admissible bases (`_transport_cost`): the farmer's
  own `transport_cost_total` for the trip, or `transport_rate_per_km_quintal`
  applied to a distance proxy. The farmer's total wins when both are given, because
  a rate path needs a proxy that does not exist for in-district markets. With
  neither, the cost stays unknown and the net stays incomplete.
* A blank component means *unknown* and a supplied `0` means *known to be zero*;
  the API never converts one into the other.

## 6. Distance and logistics

AGMARKNET publishes market *names*, not coordinates. The engine therefore
computes only the straight-line (great-circle) distance from the farm to the
**district centre** of the market's district — a documented lower-bound proxy for
out-of-district markets, unavailable for markets inside the farmer's own district
where it carries no information. It is never described as road distance or travel
time, and no travel time is shown at all. Transport cost is computed only when
the farmer supplies a ₹/quintal/km rate **and** a distance proxy exists, and is
labelled an estimate.

## 7. Sell / hold decision

Each evidence point is one verified fact with a direction (`sell`/`hold`/
`monitor`/`neutral`) and a weight; the decision is the weighted direction, and
`decision_basis` prints the weights. The ±2 % deadband
(`DIRECTIONAL_DEADBAND_PCT`) decides whether a trend or forecast counts as a
directional fact at all.

Critically, **crop-catalog attributes cannot create a decision**: a storable crop
with no observed market or risk fact returns `INSUFFICIENT_DATA` instead of
"WAIT". At least one of trend, forecast, volatility, farmer-reported storage or a
Phase 5 risk must be present. Every missing input is listed in
`missing_information`, and `SELL_NOW`/`WAIT` set
`requires_expert_confirmation`.

Phase 5 risk enters at most once per risk type, only when the stored assessment
is `elevated`/`high`/`critical`, mapped through a documented `_risk_effect`
table. Production-side risks that affect expected volume rather than timing are
reported as context.

## 8. Confidence

Every payload carries `confidence.status = "not_calibrated"` with the basis
stated in words. No accuracy, probability or calibration figure is claimed
anywhere, because no validated market-outcome dataset has been used to calibrate
the engine.
