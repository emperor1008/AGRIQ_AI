# Phase 6 Source Audit — Farm-to-Market Optimizer

Branch: `main` (working tree, **uncommitted**)
Baseline: Phase 5 end state (`0006_risk_assessment_provenance`, 320 tests green,
changes uncommitted)
Audit date: 2026-09-25
Auditor: automated (flake8, compileall, Alembic up/down, full pytest suite,
secret-pattern scan, fabrication-pattern scan, `validate_project.py`,
`check_environment.py`, live server + browser playtest of the real farmer flow)
+ manual review

## Scope

Phase 6 is **additive**. It reuses the existing farmer profile, crop-cycle,
catalog, weather, Phase 5 risk and AGMARKNET integrations, and the existing
design system. No existing route, response field, table, page, env var or
workflow was removed or re-pointed.

| Item | Before this work | After |
| --- | --- | --- |
| Routes | 63 | **69** (7 additive `/api/v1/market/*`; inventory in `phase6_route_inventory.txt`) |
| Migration head | `0006_risk_assessment_provenance` | unchanged (Phase 6 needs no schema change) |
| Tests | 320 | **399 collected — 398 passed, 1 skipped** (77 new Phase 6 tests: 41 unit + 36 integration) |
| Lint (`flake8 --select=F,E9 apps/api/agriq`) | clean | clean |
| `validate_project.py` | PASSED | PASSED (68 files, 181 modules, 9 legacy routes, 6 CSS modules) |

## Files added

| File | Purpose |
| --- | --- |
| `agriq/domain/market/{__init__,normalization,freshness,trend,forecasting,suitability,decision}.py` | pure engines: normalization/quarantine, freshness provenance, trend/volatility, chronological forecasting, agronomic suitability, economics/sell-hold/comparison |
| `agriq/services/market_intelligence.py` | orchestration: farmer context → provider + stored history → engines → payloads |
| `agriq/api/market_intel.py` | the 7 routes (parse, authorise, call, serialise only) |
| `agriq/templates/dashboard/_market.html`, `apps/web/static/js/market-panel.js` | the Farm-to-Market panel |
| `tests/unit/test_market_domain.py`, `tests/integration/test_market_intel.py` | Phase 6 tests (fixtures are in-memory AGMARKNET-shaped rows, never shipped) |
| `docs/market-{intelligence,engine,api,data-sources}.md`, this audit, `phase6_route_inventory.txt` | documentation |

Modified: `services/market_service.py` (read-only `stored_history()`),
`app_factory.py` (blueprint + shared analysis rate limit), `services/copilot_orchestrator.py`
(market/crop-choice intents, structured evidence, `_get_market` import fix),
`domain/advisory/intent.py`, `templates/dashboard/index.html`, `templates/base.html`,
`web/static/css/components.css`, `web/static/js/api-client.js`, plus the
Phase 5 files from the previous session.

## Gaps closed, and the honesty rules that bound them

1. **No fabricated numbers anywhere in the deliverable.** Prices, trend,
   volatility, forecasts, demand, transport cost, net value, yields, suitability
   and confidence are all either real stored official records, arithmetic over
   them, or an explicit unavailable/insufficient state. Verified by a
   fabrication-pattern scan (`dummy|fake|fabricat|lorem|TODO|placeholder|hardcod|random.`)
   over every Phase 6 file and by the single-legitimate-writer check for
   `MarketPriceRecord` (only `market_service._persist_record`).
2. **Demand stays unavailable** — the configured resource publishes prices, not
   arrivals, so the API answers `arrivals_not_published_by_configured_source`
   with `classification: null` instead of a proxy percentage.
3. **Forecast only from real history, evaluated chronologically** — train <
   validation < test, selection on validation only, and the prediction interval
   is built from **out-of-sample** dispersion (the test block never leaks into
   it). Below `MIN_OBSERVATIONS = 21` the answer is `insufficient_data` with the
   counts and the location scope it used.
4. **Gross ≠ net** — a net value is published only when quantity and every cost
   component exist; otherwise `NET_VALUE_INCOMPLETE` naming the missing
   components. No freight/input-cost/yield source is invented.
5. **Timing needs evidence** — a storable crop plus one price returns
   `INSUFFICIENT_DATA`; at least one observed market or risk fact is required.
6. **Phase 5 reuse, not recomputation** — stored risk rows are read; each risk
   type enters a decision at most once through a documented mapping.
7. **No calibration claim** — `confidence.status = "not_calibrated"` on every
   market payload, including the sell/hold refusals.
8. **Provider key never leaves the server** — the evidence report neither
   contains key material nor names the key's environment variable (asserted by
   test).

## Defects found and fixed during this session

| # | Severity | Defect | Fix |
| --- | --- | --- | --- |
| 1 | Blocker (silent) | `services/copilot_orchestrator._get_market` imported a non-existent `get_market_prices`, so the copilot's market fallback always degraded to "unavailable" | import `get_mandi_prices` with the documented state default; refuse explicitly when no crop is registered |
| 2 | Blocker (silent) | `market_intelligence._cached_prices` set `TTLCache.ttl`, which `cachetools` exposes as a read-only property → `AttributeError` on **every** provider call, reported as `provider_request_failed` | rebuild the cache on configuration change and hold it per app (`current_app.extensions`), so one app cannot inherit another's cached failure |
| 3 | Blocker (UI) | duplicate `id="farmForm"` (analysis form vs farm-registration form) meant `farmer-data.js` bound the wrong form: "Register Farm" did a plain GET, so no farmer could create farm → field → crop cycle, leaving the market panel permanently empty | renamed the analysis form to `analysisForm` and updated `leafscan.js`; verified by creating a farm/field/crop cycle in the browser |
| 4 | Blocker (UI) | `market-panel.js` read the farmer-context payload as `ctx.field` instead of `payload.context.field`, so the panel never initialised (permanently "Register a crop cycle…") | read the nested `context` (same shape `assistant.js` uses); a failed read now reports a load failure instead of blaming the farmer |
| 5 | Same bug, existing panel | `risk-panel.js` had the identical mistake and never picked up the field | same one-line fix |
| 6 | Misleading feedback | crop-options view printed "Freshness unavailable" although it carries per-option provenance only | render the metadata row only when the payload carries a provenance block |
| 7 | Inconsistent statement | sell/hold refusals returned no `confidence` block, so the panel fell back to "Confidence: unavailable" | one `_confidence_block()` helper used by all three sell/hold returns |

## Post-audit follow-up: economics in the panel (SPEC §26/§27/§32)

The audit's most-valuable-next item was that economics existed only in the API, so
a farmer never saw a gross value, and the §27 net-value path was unreachable: with
only a ₹/quintal/km rate, an in-district market has no distance proxy, so
`transport_cost_total` could never be supplied and every row stayed
`NET_VALUE_INCOMPLETE` forever.

* `domain/market/decision.py` — new `_transport_cost()` with the two admissible
  bases (farmer's own total, or rate × distance proxy) and their documented
  `transport_cost_basis` strings; the farmer's total wins, because a rate needs a
  proxy that does not exist in-district.
* `api/market_intel.py` — `_optional_number()`/`_query_float()` now take
  `allow_zero`: a **blank field stays unknown** and withholds the net value, while
  an explicit **`0` is a real known cost**. Quantity remains strictly positive.
  New accepted field `transport_cost_total` (overview + logistics).
* `templates/dashboard/_market.html` + `web/static/js/market-panel.js` — a
  "Sale details for a cost check" block (quantity, rate, freight total, input cost,
  market fee, three-state storage answer) and a **Compare markets & costs** action
  that renders a gross/net card. **No input ships with a value**: the panel omits
  blank fields rather than sending zero, and storage is `Not stated` by default so
  "no storage" is never assumed.

New tests: `test_farmer_supplied_costs_complete_the_net_value`,
`test_negative_cost_components_are_rejected`,
`test_market_panel_asks_for_sale_details_without_prefilling_them`,
`test_a_farmer_supplied_freight_total_completes_the_net_without_any_distance`,
`test_a_farmer_supplied_freight_total_wins_over_the_derived_rate`.

## Verification log (all commands run in this session)

```bash
# full suite
cd apps/api && python -m pytest                       # EXIT=0, 394 collected, 393 passed, 1 skipped
cd apps/api && python -m pytest tests/unit/test_market_domain.py tests/integration/test_market_intel.py   # 72 passed

# after the economics-UI follow-up (see the post-audit section below)
cd apps/api && python -m pytest -q                    # EXIT=0, 399 collected, 398 passed, 1 skipped
cd apps/api && python -m pytest tests/unit/test_market_domain.py tests/integration/test_market_intel.py   # 77 passed

# gates
python -m flake8 apps/api/agriq --select=F,E9 --max-line-length=120   # clean
python -m compileall -q apps/api/agriq apps/api/tests                 # OK
python scripts/validate_project.py                                    # PASSED
python scripts/check_environment.py                                   # all checks passed
# Alembic chain (CI-parity): upgrade head → downgrade base on a temp SQLite DB  # "Migration chain OK."

# live surface (throwaway temp DB; never agriq.db)
DATABASE_URL=sqlite:///<temp>/phase6_playtest.db AGRIQ_SECRET_KEY=… python run.py
```

Browser playtest of the real flow (register → profile → farm → field → crop
cycle → dashboard panel):

- empty state: "No official market record is available for this crop and district yet."
- logged out/empty provider: `provider.reason = api_key_not_configured` shown, no price invented;
- human-readable panel: crop label "Rice · Paddy Block", trend badge, per-market rows;
- "Sell or wait?": evidence list, missing information, "Confidence not calibrated — no probability is claimed.", expert-confirmation note;
- "Crop options": ranked statuses with the first reason each and `no stored price` where no record exists;
- impatience double/triple-click: one request, no duplicate render, no error;
- reload mid-request: panel recovers, `aria-busy=false`, buttons re-enabled;
- API-level through the same session: `demand` unavailable, `forecast` ok with
  `selected_model`, dispersion and `beats_naive_baseline`, `evidence` (45 accepted,
  0 quarantined), `logistics` → `NET_VALUE_INCOMPLETE` with `gross_value` and
  `missing_costs`, bad horizon → 400, missing CSRF → 400.

Playtest fixtures (AGMARKNET-shaped rows) were inserted **only** into the
throwaway temp database to exercise the populated render path; the seeder was
deleted afterwards and nothing was written to `agriq.db`.

## Known limitations (honest, by design)

- Demand/arrivals, freight rates, market coordinates, yields and input costs have
  no verified source in AGRIQ → those capabilities stay unavailable or
  farmer-supplied. This is recorded in the payloads, the docs and the tests.
- Stored price history depth equals deployment collecting time; a young
  deployment truthfully reports `insufficient_data` for trend/forecast.
- Distance is a straight-line proxy to a market's district centre, unavailable
  inside the farmer's own district; it is never presented as road distance.
- No calibration or accuracy figure is claimed anywhere.

## Out-of-scope defects observed (not changed)

- `apps/web/static/js/image-analysis.js:37` calls an undefined global (`AGRIQ.api`
  where the codebase defines `AgriqAPI`), raising a `ReferenceError` on every
  dashboard load (Phase 4 code). Fixing it would also switch the image-upload
  capability probe on, which is a behaviour change outside this phase's scope.
- `GET /api/v1/risk/fields/<id>/current` returns 404 when no run exists; the risk
  panel treats that as an error state. Pre-existing convention, unchanged.
