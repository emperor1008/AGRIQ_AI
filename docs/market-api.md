# Market API (Phase 6)

All endpoints are session-authenticated; the user id always comes from the server
session (never from the request body). The state-changing routes require the CSRF
header (`X-CSRF-Token`). A foreign `field_id`/`crop_cycle_id` returns **404** —
indistinguishable from a missing resource. These routes are additive: the
Phase 1 `GET /api/market-prices` route is unchanged.

Base URL (local): `http://127.0.0.1:5000`
Rate limiting: the five analysis routes share the existing analysis budget
(`AGRIQ_RATE_ANALYSIS`, default `20 per minute`).

Common failure shapes:

| Situation | Response |
| --- | --- |
| No session | 404 (app-wide convention: signed-out routes are invisible) |
| Missing/invalid CSRF on POST | 400 |
| Bad numeric input, unsupported horizon, non-list/oversized `crops` | 400 with a specific message |
| Foreign field/crop cycle | 404 |
| No crop cycle and no `commodity` | `200 {"ok": false, "status": "insufficient_data", ...}` |
| Unexpected service degradation | `200 {"ok": false, "status": "unavailable", ...}` — never a fabricated value |

### Cost and quantity inputs (overview + logistics)

These are the farmer's own figures. AGRIQ has no verified freight, input-cost or
yield source and never estimates them.

| Field | Meaning | Range |
| --- | --- | --- |
| `quantity_quintals` | quintals the farmer plans to sell | > 0, ≤ 1 000 000 |
| `transport_rate_per_km_quintal` | ₹ per km per quintal | ≥ 0, ≤ 1 000 |
| `transport_cost_total` | total freight the farmer pays for the trip | ≥ 0, ≤ 100 000 000 |
| `input_cost_total` | input cost so far, in ₹ | ≥ 0, ≤ 100 000 000 |
| `market_fee_total` | market fee or commission, in ₹ | ≥ 0, ≤ 100 000 000 |

* **Blank means unknown.** A field left out is *not* zero: the net value is withheld
  and reported as `NET_VALUE_INCOMPLETE` with `missing_costs` naming exactly what
  is absent. Nothing is ever defaulted on the farmer's behalf.
* **An explicit `0` is a real value** — no commission paid, no freight paid — and
  counts as a *known* cost.
* **Freight precedence:** when both are supplied, `transport_cost_total` is used and
  `transport_rate_per_km_quintal` is ignored. The rate path needs a distance proxy,
  which does not exist for markets inside the farmer's own district; the total works
  there because it is the farmer's own figure. `transport_cost_basis` states which
  path produced the number.
* A negative value on any of these fields returns **400**.

---

## GET /api/v1/market/overview

Prices, trend, volatility, demand state and per-variety market comparison.

Query parameters (all optional): `field_id`, `crop_cycle_id`, `commodity`,
`quantity_quintals` (> 0, ≤ 1 000 000), `transport_rate_per_km_quintal`
(≥ 0, ≤ 1 000), `transport_cost_total` (≥ 0, ≤ 100 000 000), `provider`
(`0`/`false`/`no` disables the live provider call).

Response (abridged):

```json
{
  "ok": true,
  "capability": "market_overview",
  "crop": "Rice",
  "price_unit": "INR_per_quintal",
  "provenance": {"source": "AGMARKNET via data.gov.in", "freshness_status": "aging", "is_live": false},
  "provider": {"available": false, "reason": "api_key_not_configured"},
  "latest_prices": [
    {"market": "Cuttack Mandi", "variety": "Common", "modal_price": 2180.0,
     "price_date": "2026-09-22", "source": "AGMARKNET via data.gov.in"}
  ],
  "trend": {"status": "ok", "direction": "rising", "change_percent": 4.1},
  "volatility": {"status": "ok", "band": "medium", "swing_percent": 6.3},
  "demand": {"available": false, "reason": "arrivals_not_published_by_configured_source"},
  "comparison": {"status": "ok", "groups": [{"commodity": "rice", "variety": "Common", "markets": []}]},
  "limitations": ["Official AGMARKNET provisional daily prices, not live quotes."]
}
```

An empty `latest_prices` with `trend.status = "insufficient_data"` is the honest
answer when nothing official is stored yet.

## GET /api/v1/market/forecast

Chronological forecast over stored official history.

Query parameters: `field_id`, `crop_cycle_id`, `commodity`,
`horizon_days` (7 or 14, default 7), `provider`.

Response (abridged):

```json
{
  "ok": true,
  "capability": "price_forecast",
  "horizon": "7_days",
  "observations": 43,
  "model_version": "agriq-price-forecast-v1",
  "forecast": {
    "status": "ok",
    "selected_model": "trend_seasonal",
    "forecast": [{"date": "2026-09-26", "modal_price": 2199.4}],
    "prediction_interval": {"lower": 2150.2, "upper": 2248.6, "dispersion": 18.4,
                            "interval_method": "normal approximation from out-of-sample residual dispersion"},
    "training_period": {"from": "2026-08-05", "to": "2026-09-11"},
    "validation_period": {"from": "2026-09-12", "to": "2026-09-18"},
    "evaluation_period": {"from": "2026-09-19", "to": "2026-09-25"},
    "metrics": {"reported_block": {"kind": "test", "candidates": {"moving_average_7": {"mae": 12.1, "rmse": 15.3}}},
                "selected_model": "moving_average_7", "beats_naive_baseline": true}
  }
}
```

With too little history `forecast.status` is `insufficient_data`,
`forecast.forecast` is `[]`, `prediction_interval` is `null`, `reason` names the
counts and the location scope, and `limitations` repeats them.

## GET /api/v1/market/demand

The demand capability state. The configured official resource publishes prices,
not arrival quantities, so this is deliberately unavailable:

```json
{"ok": true, "capability": "demand",
 "demand": {"available": false, "reason": "arrivals_not_published_by_configured_source",
            "classification": null, "would_require": "An official arrival-quantity series …"}}
```

## GET /api/v1/market/evidence

Provenance, freshness and data-quality report for the farmer's crop.

```json
{"ok": true, "capability": "market_evidence",
 "provenance": {"record_count": 43, "freshness_status": "aging"},
 "sources": [{"name": "AGMARKNET daily mandi prices", "resource_id": "9ef84268-…", "unit": "INR_per_quintal"}],
 "freshness_policy": {"classifier": "domain.risk_engine.freshness.classify (input kind 'market')",
                      "fresh_max_hours": 24, "aging_max_hours": 72, "stale_max_hours": 240},
 "data_quality": {"accepted": 43, "quarantined": 1},
 "quarantined_records": [{"reason": "missing_modal_price"}]}
```

The payload contains no key material and does not name the provider's
environment variable.

## POST /api/v1/market/crop-options

Crop-choice intelligence for the district (suitability first, then verified price
context). CSRF required.

Body (all optional): `field_id`, `crop_cycle_id`, `season`, `crops`
(list of strings, ≤ 12), `include_market` (bool — enables the live provider call;
off by default so evaluating many crops is not one API request per crop).

```json
{"ok": true, "capability": "crop_options", "district": "Cuttack", "season": "Kharif",
 "options": [{"rank": 1, "crop": "rice", "recommendation_status": "suitable",
              "reasons": ["…"], "supporting_evidence": ["…"],
              "market": {"price_context_available": true, "latest_modal_price": 2180.0,
                         "price_unit": "INR_per_quintal"},
              "provenance": {"freshness_status": "aging"}}],
 "risk_context": [],
 "confidence": {"status": "not_calibrated"}}
```

`recommendation_status` is one of `suitable`, `marginal`, `unsuitable`,
`insufficient_data`; ranking is by status then verified price — no opaque score.

## POST /api/v1/market/sell-hold

Timing decision support. CSRF required.

Body (all optional): `field_id`, `crop_cycle_id`, `commodity`, `market`
(restrict to one market name), `storage_available` (true/false),
`horizon_days` (7 or 14).

```json
{"ok": true, "capability": "sell_hold", "decision": "WAIT",
 "evidence": [{"kind": "trend", "observation": "Official records rose 4.1% across 9 observation dates.",
               "direction": "hold", "weight": 1.0}],
 "missing_information": ["storage availability (farmer-reported)"],
 "risks": [{"risk_type": "market_price_movement", "status": "elevated"}],
 "decision_basis": "Weighted evidence: sell 1, hold 2.5, monitor 0.5.",
 "confidence": {"status": "not_calibrated"},
 "requires_expert_confirmation": true}
```

`decision` is `SELL_NOW`, `WAIT`, `MONITOR` or `INSUFFICIENT_DATA`. Without at
least one observed market or risk fact it is always `INSUFFICIENT_DATA`.

## POST /api/v1/market/logistics

Market comparison with distance proxies and honest cost completeness. CSRF
required. Same body parameters as the overview query string
(`quantity_quintals`, `transport_rate_per_km_quintal`, `transport_cost_total`,
`input_cost_total`, `market_fee_total`) — see
[Cost and quantity inputs](#cost-and-quantity-inputs-overview--logistics) for the
blank-versus-zero rule.

```json
{"ok": true, "comparison": {"status": "ok", "groups": [{"commodity": "rice", "variety": "Common",
   "markets": [{"market": "Puri Mandi", "modal_price": 2210.0, "distance_km": 58.3,
                "distance_basis": "straight-line distance from the farm to the market district centre",
                "estimated_transport_cost": 874.5,
                "transport_cost_basis": "Farmer-supplied rate applied to the straight-line distance proxy; not a quoted freight rate.",
                "economics": {"status": "incomplete", "label": "NET_VALUE_INCOMPLETE",
                              "gross_value": 22100.0, "estimated_net_value": null,
                              "missing_costs": ["input_cost_total", "market_fee_total"]}}]}]}}
```

A row never reports a net value while a cost component is missing, and cost
components can only come from the request (AGRIQ has no verified freight or
input-cost source).
