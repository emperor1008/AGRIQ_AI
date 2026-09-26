# AGRIQ AI — Dashboard heuristics (documented formulas)

Status: **rule-based heuristics, not validated models** (`HEURISTIC_NOT_VALIDATED`).

This document exists because of two Phase 7 requirements:

- **§13** — if a numerical priority/score is used, document the formula.
- **§55** — documentation must reflect the actual implementation, and must not
  claim unsupported capability.

Everything below is reproduced from the code at the paths named. These values
appear on the farmer dashboard (`POST /dashboard` → `services.farm_intelligence.analyze_farm`).
They are **hand-weighted rules over farmer-entered values plus verified weather**.
None of them has been trained, calibrated or validated against outcomes, and
none is a field measurement. The UI must therefore always show the label next to
the number — never a bare percentage.

Guarded by `apps/api/tests/unit/test_phase7_honest_states.py`, which pins the
formulas so relabelling can never silently change a published number.

---

## 1. Risk score (0–100)

`domain/risk/scoring.py::component_scores` → summed in
`services/farm_intelligence.py::analyze_farm`, clamped to 0–96.

| Component | Formula | Bound |
| --- | --- | --- |
| Humidity | `(humidity − crop.humidity_risk + 20) × 1.35` | 0–28 |
| Rainfall | `(rain / max(crop.rainfall_risk, 1)) × 18` | 0–22 |
| Temperature | `degrees_outside_crop.ideal_temp × 4.2` | 0–18 |
| Crop Sensitivity | `crop.sensitivity × 1.9` | 4–18 |
| District Factor | coastal +5 if humidity ≥ 78; western +4 if temp ≥ 34; highland +3 if rain ≥ 12 | 0–8 |
| Leaf Evidence | LeafScan `evidence_score` | 0–22 |
| Growth Stage | `domain/risk/adjustments.py::growth_stage_adjustment` | table |
| Field Condition | `domain/risk/adjustments.py::field_condition_adjustment` | table |

**Weather components are omitted entirely when verified weather is unavailable**
— they are never filled with substitutes, so the displayed score covers only the
evidence that exists.

Displayed as: `"{score}% risk • rule estimate"`.

---

## 2. Crop health index (18–96)

`scoring.py::crop_health`

```
100 − risk×0.58 − (leafscan_evidence_score × 0.25 if an image was screened else 0)
```

clamped to **18–96**. Shown on the "Crop Health" summary card with the label
**"Rule estimate — not measured"**.

## 3. Yield protection index (20–97)

`scoring.py::productivity_score`

```
100 − int(risk×0.52)
  − 5  if humidity > 82
  − 6  if rain > 24
  − 3  if growth stage contains "flower" or "fruit"
```

clamped to **20–97**. Shown on the "Yield Protection" summary card with the label
**"Rule estimate — not a yield forecast"**.

## 4. Indicative loss band

`scoring.py::yield_loss_band`

```
low  = max(2, score × 0.12)
high = min(48, low + 8 + score × 0.06)
```

Status `YIELD_IMPACT_NOT_MEASURED`. **AGRIQ holds no measured or modelled yield
for these crops**, so this is an indicative band derived from the risk score
alone. It is labelled "If untreated (indicative band, not a measurement)" and the
card badge reads "Indicative bands — not measured".

## 5. Early-action scenario

`domain/risk/recommendations.py::before_after`

```
after_action_risk = clamp(score − 18, 15, 88)
protection        = High (score ≥ 70) | Medium (score ≥ 45) | Low to Medium
```

There is **no treatment-response dataset** behind the −18 offset, so this is an
*illustrative* scenario, not a forecast. It is labelled
"Early-action scenario (illustrative, not a forecast)" and carries
`status = HEURISTIC_NOT_VALIDATED`.

## 6. Screening confidence (40–94)

`scoring.py::confidence_score` — status `CONFIDENCE_NOT_CALIBRATED`.

```
base = 64
+9   if verified weather available
+leafscan_confidence / 10   if an image was screened
+6   if risk score ≥ 60
+5   if the strongest component ≥ 18
−12  if verified weather unavailable
```

clamped to **40–94**. It has **never been calibrated against outcomes**, so it
must not be presented as "Confidence: NN%". The dashboard does not render it; it
is published with `confidence_status` and `confidence_basis` so any future
consumer inherits the label.

## 7. Image screening confidence (LeafScan)

`services/leaf_analysis.py` — a colour-pattern heuristic over the uploaded image
using Pillow (pixel proportions of green / yellow / brown / dark), **not** a
trained crop-disease model.

| Branch | Condition | Confidence | Status |
| --- | --- | --- | --- |
| Unclear leaf area | leaf-like pixels < 6% of the image | 38 | `IMAGE_ANALYSIS_UNCERTAIN` |
| Lesion / blight-like | brown + dark ≥ 14% | `clamp(58 + lesion, 58, 90)` | `PROBABILITY_NOT_CALIBRATED` |
| Yellowing / chlorosis | yellow ≥ 20% | `clamp(52 + yellow, 52, 86)` | `PROBABILITY_NOT_CALIBRATED` |
| No strong symptom | green ≥ 58% and lesion < 8% | 70 | `PROBABILITY_NOT_CALIBRATED` |
| Mixed early signal | otherwise | 60 | `PROBABILITY_NOT_CALIBRATED` |

No image / validation failure → `DATA_UNAVAILABLE`. Trained-model inference is a
separate, gated path (`ml/inference`, requires a registered model) that reports an
honest unavailable state until a model is approved.

## 8. Risk bands and urgency

`scoring.py::risk_status` / `risk_color` / `urgency`

| Score | Status | Colour | Urgency |
| --- | --- | --- | --- |
| ≥ 80 | CRITICAL | red | Inspect today |
| ≥ 60 | HIGH | orange | Inspect within 24 hours |
| ≥ 40 | MODERATE | yellow | Monitor for 3 days |
| < 40 | LOW | green | Normal monitoring |

`packages/shared/constants/index.json` restates these bands. That file has no
runtime consumer (see Phase 7 audit finding F-21); the Python module is the
single source of truth.

---

## What is deliberately NOT here

- **No yield forecast.** AGRIQ has no yield data source.
- **No rupee figure.** Prices come only from the AGMARKNET provider; cost and
  quantity inputs are farmer-supplied and declared as such
  (`docs/DATA_PROVENANCE.md`).
- **No calibrated probability.** Phase 5 risk probabilities are rule bands and
  carry `PROBABILITY_INTERPRETATION`; Phase 6 market confidence carries
  `status = "not_calibrated"`.
- **No model metrics.** No image model is registered (`ml/models/registry.yaml`
  is empty), so no metric is reported anywhere.

## Related documents

- `docs/DATA_PROVENANCE.md` — every source AGRIQ reads, and what it does when a
  source fails.
- `docs/risk-intelligence.md` — the Phase 5 evidence-based risk engine, which is
  the authoritative risk surface.
- `docs/market-intelligence.md` — the Phase 6 market surface.

## Audit refactor note

These heuristics predate Phase 5. Phase 5 provides the evidence-first risk
engine (`domain/risk_engine/`), and Phase 6 the market engine. Phase 7 finding
F-08 records that two risk systems currently coexist; consolidating the legacy
layer onto Phase 5 output is tracked as later Phase 7 work, not done here. This
document is the interim truth so no reader can mistake one for the other.
