# Risk API (Phase 5)

All endpoints are session-authenticated; the user id always comes from the
server session (never from the request body). Mutating routes require the
CSRF header (`X-CSRF-Token`). A foreign field/assessment id returns **404** —
indistinguishable from a missing resource.

Base URL (local): `http://127.0.0.1:5000`

---

## POST /api/v1/risk/fields/{field_id}/analyze

Run the risk engine for one owned field. Idempotent: a run inside the
30-minute window returns the stored result (`cached_run: true`); pass
`{"force": true}` to recompute.

Request (all fields optional):

```json
{
  "farm_id": 1,
  "crop_cycle_id": 41,
  "include_market": false,
  "force": false
}
```

Response (abridged):

```json
{
  "ok": true,
  "field_id": 1,
  "crop_cycle_id": 41,
  "crop": "Rice",
  "overall_status": "high",
  "cached_run": false,
  "duration_ms": 143,
  "weather_freshness": "fresh",
  "weather": {
    "available": true, "provider": "Open-Meteo",
    "observed_at": "…", "retrieved_at": "…", "freshness": "fresh"
  },
  "market": {"available": false, "reason": "not_requested"},
  "image_evidence": null,
  "assessments": [
    {
      "id": 6,
      "risk_type": "disease_conducive_weather",
      "status": "high",
      "threat": "Disease-conducive weather conditions",
      "probability": 0.77,
      "severity": "high",
      "urgency": "inspect_within_24_hours",
      "warning_lead_time_hours": 24,
      "confidence": 0.94,
      "confidence_basis": "copilot-confidence-v1 (…)",
      "reasons": ["…"], "actions": ["…"], "evidence": [{"type": "…"}],
      "data_quality": {"inputs_available": true},
      "requires_expert_confirmation": true,
      "unavailable_reason": null,
      "rule_version": "agriq-risk-rules-v1",
      "assessment_method": "rule_based",
      "probability_kind": "rule_score",
      "calibration_status": "not_validated",
      "probability_interpretation": "rule-derived screening estimate from documented thresholds — not a calibrated probability of the event occurring",
      "crop": "Rice",
      "growth_stage": "Fruiting / Grain Filling",
      "district": "Cuttack",
      "generated_at": "…", "valid_until": "…"
    }
  ],
  "analysis_generated_at": "…"
}
```

Statuses: `inactive | monitor | elevated | high | critical |
data_unavailable | insufficient_data`. `probability` and `confidence` are
independent numbers; both are `null` when inputs are unavailable.

### Provenance and interpretation

| Field | Values | Notes |
| --- | --- | --- |
| `assessment_method` | `rule_based` \| `ml` \| `hybrid` | `rule_based` for every assessment today |
| `probability_kind` | `rule_score` \| `uncalibrated_ml_probability` \| `calibrated_probability` \| `null` | `null` when no probability was produced |
| `calibration_status` | `not_validated` \| `validated` \| `not_applicable` | `not_validated` for rule scores |
| `probability_interpretation` | string \| `null` | Derived from `probability_kind`; states what the number is **not** |
| `crop`, `growth_stage`, `district` | string \| `null` | Context snapshotted at analysis time, used as evaluation dimensions |

`probability` is a **rule score**, never a calibrated event probability. A
client must not render it as an N % chance of the event happening; render
`probability_interpretation` next to the number (the dashboard does exactly
that).

Rate limit: `AGRIQ_RATE_ANALYSIS` (default 20/minute).

## GET /api/v1/risk/fields/{field_id}/current

Latest persisted (active) run for the field. 404 when nothing is stored.

```json
{"ok": true, "run_group": "hex", "assessments": ["…same shape as above…"]}
```

## GET /api/v1/risk/fields/{field_id}/history

Append-only history (superseded rows included), newest first.
`?limit=50` (max 200). 404 when the field has no stored history.

## GET /api/v1/risk/assessments/{risk_id}

One owned assessment (same serialisation as above).

## POST /api/v1/risk/assessments/{risk_id}/action

Record the farmer's response through the existing farmer-actions flow.

```json
{"action_status": "completed", "farmer_note": "Checked drainage.",
 "outcome_note": null}
```

`action_status` ∈ `planned | completed | skipped | needs_help`. Response:

```json
{"ok": true, "action": {"id": 1, "action_status": "completed",
 "farmer_note": "Checked drainage.", "outcome_note": null,
 "recommendation_id": 1}}
```

Errors: 400 invalid status, 404 foreign/missing assessment.

---

## Offline evaluation (no HTTP route)

Risk evaluation is deliberately **not** exposed over HTTP: it would either leak
cross-farmer data or require an operator-only surface on the farmer API. It runs
as an operator CLI instead:

```bash
cd apps/api
python -m agriq.cli.evaluate_risk --events /path/to/reference_events.json
python -m agriq.cli.evaluate_risk --since 2026-01-01 --out report.json
python -m agriq.cli.evaluate_risk            # prints an honest insufficient_data report
```

See `docs/risk-evaluation.md` for the protocol, the metric definitions and the
current (unvalidated) status. The CLI reads every assessment ever issued,
includes superseded rows, writes nothing to the database, and emits no farmer
identifiers.

## Legacy compatibility

The Phase 2 `POST /ask-ai`, `POST /api/v1/copilot/messages`, voice and
crop-image routes are unchanged. Risk routes are additive only.
