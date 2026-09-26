# PHASE 7 — FULL SOURCE AUDIT (STEP 1 OF PHASE 7)

Audit date: **2026-09-26**
Scope: the whole repository at branch `main` (Phases 1–6 as currently on disk, 72 uncommitted entries).
Phase 7 spec step: **§5 FIRST STEP — COMPLETE REPOSITORY AUDIT** (inspect, understand, verify — *before* changing code).

This document is the evidence base for Phase 7 planning. Nothing here is inferred from a
previous phase's claims: every statement below was re-derived from the code on disk in this
session. Where something could **not** be verified, it is marked
`NOT VERIFIED` rather than assumed correct.

---

## 1. Verified baseline

Commands run in this audit (working directory `apps/api` unless stated):

| Check | Command | Result |
| --- | --- | --- |
| Full suite | `python -m pytest -q` | **EXIT=0, 399 collected** (398 passed, 1 skipped) |
| Lint (CI rules) | `python -m flake8 agriq --select=F,E9 --max-line-length=120` | clean |
| Byte-compile | `python -m compileall -q agriq ../tests` | OK |
| Project validation | `python scripts/validate_project.py` | PASSED — 68 required files, 181 Python modules, 9 legacy routes, 6 CSS modules |
| Route inventory | `create_app(TestingConfig()).url_map` | **71 routes** registered |
| Migration chain | `apps/api/alembic.ini` (`script_location = migrations`) | `0001`…`0006_risk_assessment_provenance` = head |
| JS syntax | `node --check` on every `apps/web/static/js/*.js` | all parse |

Notes:

* **F-22 (§51, doc accuracy):** `docs/audits/phase6_route_inventory.txt` states
  `TOTAL 69 routes` and lists 69, but the application registers **71**. The file omits
  `POST /dashboard` and `POST /logout`, which are genuinely registered (and pre-existing).
  Any future "no route regression" check that trusts that file is unreliable. Verified by
  diffing the file's route lines against the live `url_map`.

* The suite is green **without** any Phase 7 work, so it is a valid regression gate for
  everything that follows.

---

## 1b. P7-1 resolution log — honest-data corrections (DONE)

The plan's first step was approved as: *relabel honestly and keep the cards*.
Nothing was redesigned, no card was removed, and no working component was
rebuilt (§6). What changed is what the numbers *claim*.

| Finding | Status | What changed | Evidence |
| --- | --- | --- | --- |
| F-02 fabricated demo submit | **FIXED** | Deleted the "Run Demo Case" control and its handler. It filled crop/district/growth-stage/field-condition with values the farmer never entered and auto-submitted the real form, so fabricated observations were persisted as farmer-reported. | `templates/dashboard/index.html`, `web/static/js/leafscan.js`, `web/static/js/app.js`; guarded by `test_dashboard_offers_no_fabricated_demo_submit` |
| F-03 uncalibrated confidence | **FIXED** | The screening band is unchanged but now ships with `confidence_status = CONFIDENCE_NOT_CALIBRATED` + `confidence_basis`. | `services/farm_intelligence.py`, `domain/risk/scoring.py`; `test_legacy_confidence_is_labelled_uncalibrated` |
| F-04 hard-coded image confidence | **FIXED** | Published with `confidence_status = PROBABILITY_NOT_CALIBRATED` + basis; low-leaf-area images are marked `IMAGE_ANALYSIS_UNCERTAIN` instead of being forced into a symptom band. | `services/leaf_analysis.py`; `test_screening_confidence_is_labelled_uncalibrated`, `test_unclear_image_is_marked_uncertain` |
| F-05 hard-coded price bands | **FIXED** | `MARKET_BASELINE` deleted (no source/citation/licence, invented fallback for unlisted crops). `market_advisory` now returns `DATA_UNAVAILABLE` with no number; `profit_impact` returns a not-estimated statement. Rupee values come only from the AGMARKNET provider. | `domain/catalogs/crops.py`, `services/farm_intelligence.py`; `test_market_band_only_via_service_context` (strengthened), `test_curated_price_table_is_gone`, `test_profit_impact_never_quotes_rupees` |
| F-06 derived yield-loss band | **FIXED** | Band kept and labelled: badge is now "Indicative bands — not measured", the row reads "If untreated (indicative band, not a measurement)", status `YIELD_IMPACT_NOT_MEASURED`. The early-action figure is labelled "illustrative, not a forecast". | `domain/risk/scoring.py`, `domain/risk/recommendations.py`, `services/farm_intelligence.py`; `test_impact_card_badge_no_longer_states_a_loss_as_fact` |
| F-07 undocumented composite scores | **FIXED** | Cards keep their numbers; every label now names the basis ("Rule estimate — not measured", "Rule estimate — not a yield forecast", "rule estimate" badge). All formulas documented verbatim. | `templates/dashboard/index.html`, `docs/dashboard-heuristics.md`; `test_screening_band_formulas_are_unchanged` pins the formulas |
| F-22 route count | **FIXED (artifact)** | `docs/audits/phase7_route_inventory_baseline.txt` is the authoritative 71-route list; the under-count is recorded in it. | regenerated from the live `url_map` |
| §3 token vocabulary | **SEEDED** | The canonical tokens and basis strings now live in one place (`core/constants.py`), and the Phase 3 surface emits them. Full cross-module emission remains P7-6. | `core/constants.py` |

**Also added:** `docs/dashboard-heuristics.md` — §13's requirement to document
any numerical priority formula, and §55's requirement that docs match the code.
It reproduces every formula above verbatim and states what is deliberately *not*
computed (no yield forecast, no rupee figure, no calibrated probability, no model
metrics).

### Verification of P7-1 (re-run after the last edit)

| Check | Result |
| --- | --- |
| `python -m pytest -q` | **EXIT=0, 420 collected** (was 399; +21 tests, none removed or weakened) |
| `python -m flake8 agriq --select=F,E9 --max-line-length=120` | clean (CI gate) |
| `python -m compileall -q agriq tests ../web` | OK |
| `node --check` on the two edited JS files | OK |
| `scripts/validate_project.py` | PASSED — 68 required files, 182 modules, 9 legacy routes, 6 CSS modules |
| `scripts/check_environment.py` | all checks passed |

**Deliberately not done in this step** (tracked, not silently dropped): F-01, the
broken `AGRIQ.api.*` image client, is P7-2; F-08 (two risk systems),
F-11/F-12 (Copilot cannot see risk or images; no action plan), F-16
(observability) and F-20 (E2E tests) are their own steps. `MARKET_BASELINE` was
deleted rather than relabelled because an unsourced rupee figure cannot be made
honest by any label — the §53 rule is that every production number must have a
legitimate source, and this one had none.

## 2. Architecture inventory and verdicts

Legend: **IMPLEMENTED** · **PARTIAL** · **BROKEN** · **MISSING** · **DUPLICATED** · **UNUSED**

### 2.1 Platform / security

| Subsystem | Location | Verdict | Evidence |
| --- | --- | --- | --- |
| Session auth, login/logout, CSRF | `core/security.py`, `api/auth*.py`, `tests/security/test_security.py` | **IMPLEMENTED** | CSRF enforced on state-changing routes (incl. `/choose-mode`, `/ask-ai`, `/logout`); tests assert rejection without/with bad token |
| Security headers, CSP, cookie flags | `app_factory.py`, security tests | **IMPLEMENTED** | `test_security_headers_present`, `test_csp_blocks_foreign_scripts`, `test_session_cookie_flags` |
| Upload validation (image) | `services/leaf_analysis.validate_upload`, `api/images.py` | **IMPLEMENTED** | extension + size + mimetype + non-empty checks; `test_upload_rejects_oversized`, `test_upload_rejects_wrong_type` |
| Audio upload validation / consent gate / circuit breaker | `services/audio_validation_service.py`, `services/voice_orchestrator.py` | **IMPLEMENTED** | consent gate → session → validation → ASR; `circuit_breaker` path returns honest unavailable |
| Rate limiting | `flask-limiter`, `AGRIQ_RATE_ANALYSIS` (20/min on the 5 analysis routes) | **IMPLEMENTED** | per-route decorators; market routes share one limit |
| Secrets hygiene | `.env.example`, CI secret scan, `test_secrets_not_in_source_tree` | **IMPLEMENTED** | no real credentials in source; production config refuses to boot without Postgres/Redis |
| Request correlation ID / structured observability | — | **MISSING** | no `request_id`, no latency, no provider/model/dataset fields; `core/logging.py` is a plain formatter |

### 2.2 Farmer data & context

| Subsystem | Location | Verdict | Evidence |
| --- | --- | --- | --- |
| Farmer profile, farms, fields, soil tests, observations, crop cycles | `models/farmer.py`, `repositories/farmer_repository.py`, `api/farmer_data.py` | **IMPLEMENTED** | 24 CRUD routes; ownership scoped by `profile_id` at repository level; foreign ids → 404 |
| Crop stage calculation | `services/crop_stage_service.py`, `tests/unit/test_crop_stage.py` | **IMPLEMENTED** | reference-versioned, reason string, farmer-confirmed stage wins |
| Canonical farmer context | `services/farmer_context.py` | **PARTIAL** — see **F-10** | `build_farmer_context()` is used by `/api/farmer-context`, `/dashboard`, `/ask-ai` and the Copilot, but hard-codes an unavailable market and carries no risk / advisory / interaction history |

### 2.3 Weather

| Subsystem | Location | Verdict | Evidence |
| --- | --- | --- | --- |
| Live weather provider (Open-Meteo) | `integrations/weather/open_meteo.py`, `services/weather_service.py` | **IMPLEMENTED** | timeouts, retries, honest unavailable; `test_weather_contract.py` (7 tests) |
| Freshness classification | `domain/risk_engine/freshness.py` | **IMPLEMENTED** | `_FRESH_HOURS={weather:1.5, market:24}` / `_AGING_HOURS={6,72}` / `_STALE_HOURS={36,240}` |
| Source labelling on any weather surface | `weather.js`, `risk-panel.js` | **IMPLEMENTED** | `test_weather_badge_always_labels_source`, `test_offline_fallback_marked_not_live` |
| Offline / cached state labelling | `weather_service` cached + `stale` flags | **PARTIAL** — see §7 | cached/stale is exposed, but there is no single `CACHED / Observed / Retrieved / Age` block across modules (§34) |

### 2.4 Risk intelligence

| Subsystem | Location | Verdict | Evidence |
| --- | --- | --- | --- |
| Phase 5 evidence-based risk engine (5 risk types) | `domain/risk_engine/{analyzers,base,thresholds,weather_input,freshness}.py`, `services/risk_service.py` | **IMPLEMENTED** | `data_unavailable` / `insufficient_data` states, evidence items with observation + retrieval timestamps, `PROBABILITY_INTERPRETATION` constant |
| Persistence + provenance migration | `models/risk.py`, `migrations/versions/0006_risk_assessment_provenance.py` | **IMPLEMENTED** | run + assessment + evidence provenance stored |
| Risk evaluation CLI (metrics, subgroups) | `cli/evaluate_risk.py`, `domain/risk_evaluation/*` | **IMPLEMENTED** | never substitutes placeholder data; refuses to report metrics it cannot compute |
| Phase 3 heuristic risk scoring (`risk` 0–100, `health`, `productivity`, `yield_loss`, `confidence`) | `domain/risk/*`, `services/farm_intelligence.py` | **DUPLICATED / non-compliant** — see **F-03, F-06, F-07, F-08** | still the primary `/dashboard` path |
| Two risk systems in one dashboard | `templates/dashboard/index.html` (legacy cards) + `_risk.html` (Phase 5 panel) | **DUPLICATED** | both render on the same page |

### 2.5 Image intelligence

| Subsystem | Location | Verdict | Evidence |
| --- | --- | --- | --- |
| Phase 4 ML pipeline (registry, ingest, validate, splits, train, evaluate, calibrate, export) | `ml/**` | **IMPLEMENTED** | real cited dataset discovery records; `approved_dataset_ids: []`; training impossible until a dataset is approved; no fabricated models (`ml/models/registry.yaml` is `models: []`) |
| Inference package with abstention + quality gates | `ml/inference/*`, `tests/unit/test_phase4_ml.py` | **IMPLEMENTED** | refuses out-of-distribution / low-quality / unsupported-crop images |
| Web image routes + honest unavailable state | `api/images.py`, `services/*`, `image-analysis.js` | **PARTIAL** | server-side honest states present; **client is BROKEN — F-01** |
| Legacy LeafScan colour heuristic "confidence" | `services/leaf_analysis.py` | **non-compliant** — see **F-04** | hard-coded numeric confidence |
| "Run Demo Case" button | `templates/dashboard/index.html:112`, `leafscan.js:12` | **BROKEN (fake production data)** — see **F-02** | fabricates district/stage/field-condition and auto-submits |

### 2.6 Voice intelligence

| Subsystem | Location | Verdict | Evidence |
| --- | --- | --- | --- |
| Consent gate, session, audio validation, ASR, transcript review, TTS | `api/voice.py`, `services/voice_orchestrator.py`, `integrations/speech/bhashini_asr.py` | **IMPLEMENTED** | provider confidence stored **verbatim**; absent confidence stays `null`; `status="unavailable"` with `error_category` (`not_configured`, `timeout`, `api_error`, `unsupported_language`); no silent provider switching |
| Voice → unified Copilot | `voice_orchestrator.py:307` → `copilot_orchestrator.run_copilot` | **IMPLEMENTED** | text and voice share one orchestration path |

### 2.7 Market intelligence

| Subsystem | Location | Verdict | Evidence |
| --- | --- | --- | --- |
| Phase 6 pure engines | `domain/market/{normalization,freshness,trend,forecasting,suitability,decision}.py` | **IMPLEMENTED** | 660-line `decision.py`; `MIN_OBSERVATIONS=21`, `SUPPORTED_HORIZONS=(7,14)`, `DIRECTIONAL_DEADBAND_PCT=2.0` |
| Orchestration + 7 routes | `services/market_intelligence.py`, `api/market_intel.py` | **IMPLEMENTED** | economics incl. blank-vs-zero costs, `transport_cost_basis`, `NET_VALUE_INCOMPLETE` |
| Provider reality | `integrations/market/agmarknet.py` | **PARTIAL** | no `DATA_GOV_IN_API_KEY` here → only `api_key_not_configured` / `provider_request_failed` observable; **success path NOT VERIFIED** |
| Distance / routing | `decision.market_distance_proxy()` | **PARTIAL** | straight-line district-centre proxy, documented `ROUTE_DATA_UNAVAILABLE`; no road distance, no travel time |
| `FRESHNESS_POLICY` restated in `market_intelligence` | vs `domain/risk_engine/freshness.py` | **DUPLICATED** | same 24/72/240 h thresholds in two places (single-source violation) |

### 2.8 Copilot / assistant

| Subsystem | Location | Verdict | Evidence |
| --- | --- | --- | --- |
| Context-aware Copilot (intent → tools → evidence → grounded LLM) | `services/copilot_orchestrator.py` (889 lines), `domain/advisory/intent.py` (19 intents) | **IMPLEMENTED** | tools `weather|market|knowledge|context`; evidence items with freshness; prompt says "use ONLY the verified context below; never invent weather, prices, soil values, diagnoses or citations" |
| Phase 6 market tools inside the Copilot | `_market_intelligence`, `_market_intel_evidence` | **IMPLEMENTED** | market records/decisions become evidence |
| Phase 5 risk inside the Copilot | — | **MISSING** — **F-11** | no reference to `risk_service` / `risk_engine` anywhere in the orchestrator |
| Phase 4 image analyses inside the Copilot | — | **MISSING** — **F-11** | symptom handling is keyword flags only (`_symptom_severity`) |
| Legacy generic Q&A path | `services/assistant_orchestrator.py` via `/ask-ai` | **DUPLICATED (intentional, undocumented)** — **F-09** | Gemini-or-curated-KB answers, no evidence chain; retained for student mode + fallback |
| Unified action plan (§12) | — | **MISSING** — **F-12** | Phase 5 emits per-assessment actions, Phase 6 emits market decisions; nothing composes them |
| Conflict resolution (§22) | — | **MISSING** — **F-13** | no `supporting_factors` / `conflicting_factors` / `uncertainties` payload |
| Data-quality gate (§24) | Phase 5 `insufficient()`, Phase 6 blocked states | **PARTIAL** — **F-15** | no shared pre-recommendation gate |

### 2.9 UI, docs, CI

| Subsystem | Verdict | Evidence |
| --- | --- | --- |
| Design system preserved, 6 CSS modules, tokens | **IMPLEMENTED** | `tokens.css`, `base.css`, `dashboard.css`, `components.css`, `responsive.css`, `animations.css`; validate_project asserts all 6 |
| Responsive breakpoints | **IMPLEMENTED** (`NOT VERIFIED` in a browser this session) | `@media` rules at 1250/1180/1150/900/700/620/560/480 px + `responsive.css` |
| Accessibility | **PARTIAL** (`NOT VERIFIED` in a browser) | `<html lang="en">`, viewport meta, `aria-label`×14, `aria-live`×12, `aria-labelledby`×2, `aria-busy`×2, `aria-pressed`×1, `prefers-reduced-motion` blocks; **no skip link found**, keyboard audit not performed |
| Unified farm dashboard (§41) | **PARTIAL** | `index.html` composes `_farm_data.html`, `_risk.html`, `_market.html`, `assistant_panel` — but alongside the legacy Phase 3 cards, and with no aggregated "today's actions" block |
| Docs | **IMPLEMENTED (extensive)** | 32 doc files incl. per-phase API/engine/provenance/evaluation docs; audits for Phases 4/5/6 |
| CI gates | **IMPLEMENTED** | compileall, flake8 (F,E9), secret scan, validate_project, check_environment, Alembic up/down on temp SQLite, unit/integration/full suites, Bandit **failing on HIGH/MEDIUM** (not suppressed) |
| JS/TS checks in CI | **MISSING** | no `node --check`, no JS lint, no frontend tests, no `package.json` anywhere |
| Dependency audit | **MISSING** | no `pip-audit` / licence step |

---

## 3. Findings register

Severity: **S1** = farmer-visible false or broken intelligence · **S2** = architectural/contract gap · **S3** = hygiene/docs/dead code.
Classification: **PRODUCTION** · **TEST ONLY** · **DOC ONLY** · **DEV ONLY**.

### S1 (farmer-visible)

**F-01 — `BROKEN`: image-analysis client calls an undefined global.** *(PRODUCTION, §15/§51)*
`apps/web/static/js/image-analysis.js:37,68,143,153` call `AGRIQ.api.imageCapabilities()`,
`AGRIQ.api.analyseCropImage()`, `AGRIQ.api.sendImageFeedback()`,
`AGRIQ.api.requestImageExpertReview()`. The global created by
`apps/web/static/js/api-client.js:306` is **`AgriqAPI`**, with those four methods **at the top
level** (`imageCapabilities`, `analyseCropImage`, `sendImageFeedback`,
`requestImageExpertReview`) — there is no `.api` namespace. `AGRIQ` is defined **nowhere**
in `apps/web/` or `apps/api/agriq/templates/` (grep-verified). Live console observation from an
earlier playtest confirms `ReferenceError: AGRIQ is not defined` on dashboard page load.
Effect: the entire crop-image panel is dead in the browser (capabilities, upload, feedback,
expert review) even when the server is healthy.
Fix: rename the four call sites to `AgriqAPI.*`; add a CI JS syntax check so this class of
defect cannot ship again.

**F-02 — `BROKEN (fake production data)`: "Run Demo Case" injects fabricated field context and auto-submits.** *(PRODUCTION, §2/§4/§52)*
`templates/dashboard/index.html:112` exposes `<button onclick="runDemoCase()">Run Demo Case</button>`.
`web/static/js/leafscan.js:12 runDemoCase()` sets `crop=Rice`, `district=Cuttack`,
`growthStage=Vegetative`, `fieldCondition="Humid field"` — values the farmer never entered —
then calls `form.submit()` (line 25) on the real LeafScan form, so the fabricated context is
processed and persisted as if farmer-reported. This is precisely the §52 "PRODUCTION" class the
Phase 7 spec requires removing, and it contradicts the §4 rule that fixtures must never enter a
production path.
Fix: remove the button and the demo function (keep the rest of LeafScan), or replace with an
explicitly labelled, non-persisting sample-image preview that carries no fabricated context.

**F-03 — `PARTIAL`: uncalibrated `confidence` shown on the main farmer dashboard.** *(PRODUCTION, §31/§3)*
`services/farm_intelligence.py:148` emits `"confidence": confidence_score(...)`, and
`domain/risk/scoring.py:136-152` computes it from a **hard-coded base of 64.0** adjusted by
integers (weather +9, leafscan +conf/10, score≥60 +6, strong component +5, no weather −12),
clamped to 40–94. No calibration procedure, no calibration dataset, no reliability curve, and no
label. Phase 5 already owns the honest vocabulary (`domain/risk_engine/base.py`
`PROBABILITY_INTERPRETATION`); this legacy path does not use it.
Fix: stop presenting a bare percentage — attach an explicit non-calibrated status and basis, or
show Phase 5's confidence status where a Phase 5 assessment exists.

**F-04 — `PARTIAL`: hard-coded image "confidence".** *(PRODUCTION, §15/§31)*
`services/leaf_analysis.py` returns `"confidence"` values `38` (line 113), and via
`clamp(58 + int(lesion), 58, 90)` (132) / `clamp(52 + int(yellow_pct), 52, 86)` (136) / `70`
(140) / `60` (144). The module docstring is honest that this is a colour-pattern heuristic and
"never diagnosis", but the numeric field is named `confidence` and is presented alongside real
evidence, so it reads as a model confidence. `IMAGE_ANALYSIS_UNCERTAIN` (§15) has no
implementation.
Fix: keep the screening value, but rename its meaning in the payload (status + basis), and add
the uncertain state for the low-leaf-area case.

**F-05 — `PARTIAL`: hard-coded price bands presented as advisory prices.** *(PRODUCTION, §26/§53)*
`domain/catalogs/crops.py:10 MARKET_BASELINE` is a 26-crop ₹/quintal table with **no source,
citation, retrieval date, licence or update frequency**. It is rendered at
`farm_intelligence.py:48` as `"range": "₹low - ₹high / quintal"` and at `:66` as
`"₹low - ₹high / acre if untreated"`. Both use an **invented fallback `(1200, 3200)`** for any
crop not in the table (lines 48, 66). Some values are plausible MSP-ish figures, but "plausible"
is not provenance.
Fix: either record real provenance (official source + URL + retrieval date) or stop presenting
ranges as prices and return an honest unavailable state; **remove the invented fallback** in all
cases.

**F-06 — `PARTIAL`: derived "yield loss" band.** *(PRODUCTION, §2 "NO FABRICATED YIELD")*
`domain/risk/scoring.py:130 yield_loss_band(score)` invents `"{low}% - {high}%"` from the score
alone; surfaced as `yield_loss` (`farm_intelligence.py:146`), rendered as a card badge
(`:220`) and a "Yield Impact" chip (`index.html:129`).
Fix: either document it as a heuristic band with an explicit non-measured label, or replace with
a not-measured state.

**F-07 — `PARTIAL`: composite 0–100 scores from undocumented hard-coded weights.** *(PRODUCTION, §2/§13)*
`domain/risk/scoring.py`: `crop_health` (112, penalty ×0.58, clamp 18–96), `productivity_score`
(117, 0.52, hard-coded humidity>82 / rain>24 / flowering deductions, clamp 20–97),
`component_scores`, `risk_status` bands (24, 80/60/40). Surfaced as `risk`, `health`,
`productivity`. No §13 prioritization formula is documented and none of these are validated.
Fix: document the formula verbatim in `docs/`, label the outputs as unvalidated heuristics, and
let the unified action plan prefer Phase 5 assessments.

**F-08 — `DUPLICATED`: two live risk systems.** *(PRODUCTION, §6/§7/§63)*
`domain/risk/*` (Phase 3 heuristic) and `domain/risk_engine/*` + `services/risk_service.py`
(Phase 5 evidence-based) both run in production, and both render on `/dashboard`. §63 requires
that no duplicate major systems exist.
Fix: make `risk_engine` the single risk authority; reduce the Phase 3 layer to an explicitly
scoped symptom/field screening presenter, or have it consume Phase 5 output.

**F-11 — `MISSING`: the Copilot cannot see Phase 5 risk or Phase 4 image analyses.** *(PRODUCTION, §19/§21)*
`grep` over `services/copilot_orchestrator.py` finds no `risk_service` / `risk_engine` reference
and no crop-image analysis reference; its tools are weather, market, knowledge and context.
Therefore the §21 chain (crop → stage → weather → disease-conducive conditions → risk → market →
action) cannot be produced.
Fix: add risk and image evidence to the Copilot's context retrieval, with evidence items that
carry source + observation/retrieval timestamps.

### S2 (architectural / contract)

**F-10 — `PARTIAL`: the canonical farmer context is stale and incomplete.** *(PRODUCTION, §7/§8)*
`services/farmer_context.py:134-138` **hard-codes** `context["market"] = {"available": False,
"reason": "not_requested", "message": "Official matching records unavailable."}` although Phase 6
exists; the object also has no `risk`, no advisory history and no interaction history, while §7
lists weather / risk history / market / advisory / interaction as context sections. The Copilot
works around this with its own `_get_market()`, so the same farmer has two different market
truths depending on the entry point.
Fix: make the context consult Phase 6 and Phase 5 (or explicitly name sections as not built in
this pass), and keep one market truth.

**F-12 — `MISSING`: unified Farm Action Plan (§12).** No service composes crop cycle + weather +
risk + image + water + market + logistics into the §12 shape
(`priority, action, reason, evidence, source, urgency, data_freshness, limitations`).

**F-13 — `MISSING`: conflict resolution (§22).** No module reports
`supporting_factors` / `conflicting_factors` / `uncertainties`. Phase 6 `sell_hold` has partial
"for/against" evidence; nothing spans modules.

**F-14 — `DUPLICATED` + `PARTIAL`: freshness orchestration (§23).**
`market_intelligence.FRESHNESS_POLICY` restates 24/72/240 h that `domain/risk_engine/freshness.py`
owns. Individually correct, but not single-source, and no aggregate response reports per-source
freshness (weather fresh / market 2 h / risk 20 min / crop profile user-entered).

**F-15 — `PARTIAL`: data-quality gate (§24).** Phase 5 `insufficient()` and Phase 6 blocked
states exist; there is no shared gate that can block a *combined* recommendation with
`RECOMMENDATION_BLOCKED_INSUFFICIENT_DATA`.

**F-16 — `MISSING`: observability (§44).** No request id, endpoint/service/provider latency,
error taxonomy, model version or dataset version in logs.

**F-17 — `PARTIAL`: dataset registry (§26/§27).** `ml/data/dataset_registry.yaml` +
`ml/data/registry.py` are real and honest: cited sources, `licence`, `licence_verified`,
`reviewer`, `checksum`, `known_limitations`, `status`; approval is refused without
licence + checksum + reviewer. Missing vs §26: `schema`, `collection_method`, `retrieval_date`,
`update_frequency`, `validation_status`/`approval_status` split, and explicit redistribution /
commercial-use / attribution review fields. `DATASET_NOT_APPROVED` has no runtime token.
Related: `data/source_manifest.json` is a **template** whose one entry is an
`EXAMPLE` with `https://example.org/...`. It is safe today only because ingestion is an explicit
CLI (`--manifest` is required, nothing auto-runs, rows land `pending_review`) — it must never be
ingested as-is.

**F-18 — `PARTIAL`: model governance (§29/§30/§31/§32).** `ml/models/registry.yaml` is
`models: []` (no fabricated models) and `ml/inference/registry.py` validates a required field
list incl. checksum and approval. Missing: `training_period` / `validation_period` / `test_period`
/ `features` / `target` / `metrics` / `baseline` / `deployment_date` coverage as a validated
contract, a CLI to validate registry entries, and any app-level §32 subgroup reporting
(`INSUFFICIENT_SAMPLE_SIZE`).

**F-19 — `NOT MEASURED`: performance (§39).** No instrumentation exists, so no latency claim can
be made. Existing caching: per-app `TTLCache` for the market provider
(`app_factory` → `market_intel_provider_cache`), `risk_service._ttl_minutes()`.

**F-20 — `PARTIAL`: tests (§46/§48/§49).** 399 tests across 12 unit + 8 integration + 1 security
suite, including route-regression, CSRF, upload and market-honesty tests. Missing: the five §48
end-to-end journeys, the §49 no-hallucination E2E test, any frontend/JS test, and a browser-level
panel regression harness.

**F-21 — `UNUSED`/`DUPLICATED`: `packages/shared/`.** Referenced only by `README.md:243`.
`packages/shared/constants/index.json` restates risk bands (`max 39/59/79/100`) that
`domain/risk/scoring.py risk_status` owns. Currently consistent, but it is a drift hazard with no
consumer.

### S3 (hygiene / docs)

**F-09 — `DUPLICATED (intentional, undocumented)`:** `/ask-ai` (`assistant_orchestrator`, Gemini
or curated KB, **no evidence chain**) vs `/api/v1/copilot/messages`
(`copilot_orchestrator`, context + evidence). `assistant.js:200` keeps the legacy flow for student
mode and as fallback. Two answer paths with different honesty guarantees must be documented, and
§10's LLM safety rule must be asserted for both.

**F-22 — doc inaccuracy:** route inventory under-counts (see §1). Every other doc figure checked
(migration head, test count, route list, CI gates) matches the code.

**F-23 — CI/deps:** gates are real and not suppressed. Gaps: no JS syntax/lint check, no
frontend tests, no dependency audit; flake8 restricted to `F,E9` (a deliberate, documented scope).
Runtime dependencies are minimal (`Flask`, `flask-limiter`, `flask-sqlalchemy`, `alembic`,
`cachetools`, `requests`, `Pillow`, `gunicorn`, `SQLAlchemy`; dev: `pytest`, `flake8`) — §58
review found nothing unnecessary to remove. Hashing/crypto and ML training deps are correctly
absent from the runtime requirements.

---

## 4. Honest-state vocabulary matrix (§3)

Verified by grep for the canonical tokens across `apps/api/agriq`:

| Token | Where it exists today |
| --- | --- |
| `DATA_UNAVAILABLE` | `domain/risk_engine/base.py` (comment/docstring), `domain/market/decision.py` |
| `ROUTE_DATA_UNAVAILABLE` | `domain/market/decision.py` |
| `NET_VALUE_INCOMPLETE` | `domain/market/decision.py`, `api/market_intel.py` |
| `PROBABILITY_NOT_CALIBRATED` / `CONFIDENCE_NOT_CALIBRATED` | **nowhere** |
| `INSUFFICIENT_REAL_DATA` | **nowhere** |
| `MODEL_NOT_VALIDATED` | **nowhere in Python** (concept enforced by `ml/inference/registry.py` approval gating) |
| `MODEL_TRAINING_BLOCKED` / `MODEL_NOT_REQUIRED` / `INSUFFICIENT_REAL_DATA_FOR_TRAINING` | **nowhere** |
| `RECOMMENDATION_BLOCKED_INSUFFICIENT_DATA` | **nowhere in Python** (market uses its own blocked states) |
| `INSUFFICIENT_SAMPLE_SIZE` | **nowhere** |
| `DATASET_NOT_APPROVED` | **nowhere** (registry raises `RegistryError` strings instead) |
| `IMAGE_ANALYSIS_UNCERTAIN` | **nowhere** |
| `VOICE_TRANSCRIPTION_FAILED` | **nowhere** (voice uses `status="unavailable"` + `error_category`) |
| `WEATHER_DATA_UNAVAILABLE` | **nowhere** (weather uses `available: false` + `reason`) |
| `CROP_STAGE_UNKNOWN` | **nowhere** (stage uses `null` + reason) |

**Nuance, stated precisely:** honesty itself is broadly **implemented** — most modules return
explicit unavailable / insufficient states under their own names, and the Phase 6 tokens are
canonical. The gap is that §3's vocabulary is **not standardized across modules**, so a unified
consumer cannot branch on one set of states. Phase 7 should introduce the canonical tokens as the
*labels* (without discarding the existing honest semantics) rather than claim honesty is absent.

---

## 5. Phase 7 gap list vs §63 acceptance criteria

| §63 criterion | Status | Blocked by |
| --- | --- | --- |
| All modules use a unified farmer context | ✗ | F-10 |
| Copilot orchestrates existing intelligence (risk + image) | ✗ | F-11 |
| Phase 5 and Phase 6 properly integrated | ~ | F-08 (two risk systems), F-14 (freshness duplication) |
| No duplicate major systems | ✗ | F-08, F-09, F-21 |
| Every production dataset/API real, provenance + licence recorded | ~ | F-17 (fields), F-05 |
| Freshness tracked, data quality validated | ~ | F-14, F-15 |
| No dummy/synthetic production datasets | ✓ (registries clean) | F-02 is the exception in the *UI*, not a dataset |
| LLM grounded, no fabricated numbers/confidence/metrics | ✗ | F-03, F-04, F-05, F-06, F-07 |
| Text/voice/image work; multimodal context unified; failures safe | ~ | F-01 (image client broken), F-11 (no unified multimodal context) |
| Phase 5 evidence/freshness/confidence truthful | ✓ | — |
| Phase 6 real market/forecast/logistics/economics | ~ | provider success path unverified; routing is a labelled proxy |
| Security: secrets, uploads, APIs, farmer data, external requests | ✓ | — (strongest area; F-16 observability is adjacent) |
| Unit + integration + E2E + regression + CI pass | ~ | F-20 (no E2E/no-hallucination/JS tests) |
| UI preserved, responsive, accessible, no fake cards/charts/stats | ✗ | F-02, F-03, F-05, F-06, F-07 |

`✓` = verified compliant · `~` = partial · `✗` = not met.

---

## 6. Proposed Phase 7 build order

Ordered so the farmer-visible falsehoods are removed first, then integration, then assurance.
Each step is intended as the *smallest safe change* on the existing architecture (§6).

| Step | Work | Closes |
| --- | --- | --- |
| **P7-1** | Honest-data corrections on what the farmer sees today: remove the demo-case fabricated context; un-calibrate the confidence labels; stop presenting curated bands as prices and drop the invented fallback; label/neutralise the yield-loss band and composite scores | F-02, F-03, F-04, F-05, F-06, F-07 |
| **P7-2** | Fix the image-analysis client global; add a CI JS syntax check | F-01, F-23 |
| **P7-3** | Unified farmer context: Phase 5 + Phase 6 sections, single market truth, one source of truth for freshness thresholds | F-10, F-14 |
| **P7-4** | Unified Farm Action Plan service + one read route with the §12 JSON shape, a documented §13 priority formula, and a §24 quality gate that can block with `RECOMMENDATION_BLOCKED_INSUFFICIENT_DATA` | F-12, F-13, F-15 |
| **P7-5** | Copilot consumes risk + image + the action plan with §11 evidence chains; §10 safety asserted for both answer paths | F-11, F-09 |
| **P7-6** | Canonical §3 token layer emitted by all modules (labelling existing honest states, no semantic regressions) | §3 matrix |
| **P7-7** | E2E journeys (§48), no-hallucination suite (§49), frontend/JS test harness | F-20 |
| **P7-8** | Observability: request id + per-provider latency + model/dataset version, secret-safe | F-16 |
| **P7-9** | Registry completion: §26 dataset fields, §29 model fields, `DATASET_NOT_APPROVED`; dependency audit | F-17, F-18, F-23 |
| **P7-10** | Docs to match reality (§55), corrected route inventory/regression record, accessibility audit | F-21, F-22, F-23 |

### Explicitly out of scope / do not touch (verified working)

* Phase 5 risk engine internals, evidence model, `PROBABILITY_INTERPRETATION`, migration `0006`.
* Phase 6 market engines, the 7 routes, the economics semantics (blank ≠ 0, freight precedence).
* Auth/CSRF/CSP/session/upload validation — audit found no defect.
* Voice pipeline — provider confidence already verbatim; no fabrication found.
* The 6 CSS modules and the existing page structure — Phase 7 improves coherence, not design.
* `ml/` training code — no dataset is `approved`, so **training must remain impossible**; this is
  correct behaviour, not a gap.

---

## 7. Honest limitations of this audit

1. **No browser session was run in this audit.** Accessibility, responsive behaviour and the
   `ReferenceError` were read from source; the earlier playtest observation is cited as prior
   evidence, not re-measured here. All such rows are marked `NOT VERIFIED`.
2. **The market provider success path remains unexercised** — no `DATA_GOV_IN_API_KEY` is
   available in this environment, so only `api_key_not_configured` / `provider_request_failed`
   have ever been observed.
3. **No performance numbers are reported** because no instrumentation exists (F-19). Phase 7 must
   measure before optimising (§39).
4. **ML metrics are absent by design** (`models: []`, `approved_dataset_ids: []`). This audit
   makes no claim about model quality because no model is registered.
5. Line numbers refer to the working tree at audit time; they will drift as Phase 7 lands.
