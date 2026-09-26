# Phase 5 Source Audit — Crop Risk Intelligence

Branch: `main` (working tree, uncommitted)
Baseline commit: `6ce811e` ("AGRIQ V2")
Audit date: 2026-09-24
Auditor: automated (flake8, compileall, Alembic up/down cycle, full pytest suite,
secret-pattern scan, `scripts/validate_project.py`, live server + browser render
check) + manual review

## Scope

Phase 5 already shipped a working risk engine (five analyzers, thresholds,
freshness, persistence, API, dashboard panel, docs). This audit session
**extended** it rather than rebuilding it, per the preserve-first rule:

1. Recorded the baseline before changing anything: 63 routes
   (`docs/audits/phase5_route_inventory_baseline.txt`), the migration chain
   (head `0005_phase5_risk` before this change), env vars, response schemas and
   the test suite (290 passed, 1 skipped).
2. Ran the full suite on the pristine tree to confirm a green baseline.
3. Identified the genuine gaps against the Phase 5 requirements and closed them.
4. Re-ran lint, tests, migrations, project validation, a live server start and a
   browser render check of the changed UI file.

## Baseline (before this session's changes)

| Item | Baseline |
| --- | --- |
| Routes | 63 (5 additive risk routes already present) |
| Migration head | `0005_phase5_risk` |
| Tests | 290 passed, 1 skipped |
| Lint gate (`flake8 --select=F,E9`) | **53 findings — failing** |
| Frontend pages | login/choose/dashboard (+ voice, images, farm-data panels) |
| Env vars | see `.env.example` |

No existing route, page, component, table, env var, workflow or response field
was removed, renamed or changed in meaning by this session.

## Gaps found and closed

| # | Requirement | Gap | Change |
|---|-------------|-----|--------|
| 1 | §4, §7, §22, §36 — assessment method must be explicit | `assessment_method` did not exist anywhere; only `model_version`/`rule_version` hinted at provenance | Added `assessment_method` (`rule_based`), `probability_kind` (`rule_score`) and `calibration_status` (`not_validated`) to the `Assessment` contract, persistence, API and UI |
| 2 | §5, §17 — never imply a calibrated probability | A stored probability carried no statement of what it was | Added `probability_interpretation`, derived from `probability_kind`, stating the number is *not* a calibrated probability; rendered verbatim next to every likelihood |
| 3 | §13–17 — evaluation framework | Only a prose doc saying "evaluation unavailable"; no code, no metrics, no dimensions | Built `domain/risk_evaluation/` (protocol, dataset loader, metric maths, matcher), `cli/evaluate_risk.py`, and the `issued_for_evaluation` read path; reports precision/recall/F1/false-alert/missed-event/Brier/reliability/lead-time overall and by crop, stage and district, or an honest `insufficient_data` |
| 4 | §13 — district/crop/stage evaluation dimensions | Assessment rows did not record the context they were computed with | Added `crop_name`, `growth_stage`, `district` snapshots at assessment time |
| 5 | §16 — warning lead time as a measurable metric | Only a static per-type constant | Per-event `event_time`, `first_valid_warning_time` and `warning_lead_time_hours` with mean/median/min/max + bucket distribution in the evaluation report |

## Bugs discovered and automatically fixed

| # | Severity | Location | Bug | Fix |
|---|----------|----------|-----|-----|
| 1 | **High (new)** | `models/risk.py` | A column `default` coerced an explicit `probability_kind=None` into `"rule_score"`, so an *unavailable* assessment (no probability) was stored claiming a rule score — a provenance lie, the exact thing §5/§7 forbid. Caught by the new integration test. | Removed the column default; `probability_kind` is now NULL when no probability exists. Migration backfills `rule_score` only where `probability IS NOT NULL`. |
| 2 | **High** | `domain/risk_evaluation/evaluate.py` (new code) | First draft published `precision = 0.0` for a scope with no reference events, i.e. manufacturing "every warning was a false alert" from absent evidence. Caught by a unit test. | All outcome metrics (and calibration pairs) now require the scope to contain reference events; otherwise `insufficient_data` with a reason. |
| 3 | **High (pre-existing)** | `services/copilot_orchestrator.py:499` | Comprehension referenced `p` while iterating `passage` → `NameError` whenever approved knowledge excerpts were attached, breaking the copilot prompt builder. | Use `passage.*`; surfaced by the repo's own flake8 gate (F821). |
| 4 | **High (pre-existing)** | `api/dashboard.py:69` | `logger.warning(...)` in an `except` block with no `logger` defined → `NameError` replacing the graceful farmer-context degradation with a 500 on the dashboard. | Added `get_logger("api.dashboard")`. |
| 5 | **Medium (pre-existing)** | `services/weather_service.py:111,145` | `Mapping` used in annotations but never imported (F821; latent because annotations are lazy). | Imported `Mapping`. |
| 6 | **Medium (pre-existing)** | `integrations/speech/bhashini_asr.py:132` | `Optional` used in annotations but never imported (F821, latent). | Imported `Optional`. |
| 7 | **Medium (pre-existing)** | `core/config.py` | `RISK_ASSESSMENT_TTL_MINUTES` was documented in `.env.example` but never declared in config, so the documented env var had no effect. | Wired it into `BaseConfig` with sane bounds. |
| 8 | Low ×45 (pre-existing) | 25 modules | Unused imports and unused locals across the API package (F401/F841), failing the repository's own lint gate. | Removed; no behaviour change. |

All 53 lint findings were fixed rather than suppressed; the CI lint gate
(`flake8 apps/api/agriq --select=F,E9 --max-line-length=120`) is now clean.

## Regression verification

| Check | Result |
| --- | --- |
| Full test suite | **320 passed, 1 skipped** (was 290 + 1) |
| Lint (`flake8 --select=F,E9`) | clean (was 53 findings) |
| `python -m compileall` (agriq, tests, ml) | clean |
| Alembic chain | `upgrade head → downgrade 0005 → upgrade head → downgrade base → upgrade head` all OK |
| `scripts/validate_project.py` | PASSED (68 required files, 170 modules, 9 legacy routes, 6 CSS modules) |
| `scripts/check_environment.py` | all checks passed |
| Secret scan (CI parity pattern) | clean |
| Dev database migration | `run_migrations.py upgrade` applied additively to `instance/agriq.db` |
| Backend start | `python run.py` boots; `/healthz` 200, static JS/CSS 200, unauth risk route 404 (no existence leak) |
| Frontend render | risk panel renders method + interpretation with zero console errors (browser check) |
| Existing routes | all 63 registered; `test_existing_routes_still_present` + `TestRouteRegression` pass |
| Crop cycle / stage / weather / images / copilot / voice / auth / farmer data | covered by the 320-test suite, all green |

## Deliberately NOT done (require real data or product decisions)

1. **No published accuracy metrics.** The evaluation harness is implemented and
   tested, but no real, provanced reference-event dataset has been executed, so
   every metric reports `insufficient_data`. Fabricating figures is prohibited.
2. **No ML model.** No legitimately trained/calibrated risk model or dataset
   exists for this scope, so `assessment_method` stays `rule_based` and
   `calibration_status` stays `not_validated`. The fields are designed so a
   registered model can replace an analyzer without any caller guessing
   provenance.
3. **Thresholds remain screening baselines**, not Odisha-validated agronomy;
   `docs/risk-engine.md` says so explicitly.
4. **No Docker build verification** in this environment (no Docker daemon);
   the Dockerfile is unchanged by this work.

## Test-visible invariants added

* Every assessment declares an `assessment_method` in `rule_based | ml | hybrid`.
* A non-null probability from the rule engine must be `rule_score` with
  `calibration_status = not_validated`.
* An assessment with no probability stores `probability_kind = NULL`.
* The API must return the interpretation wording, and it must contain
  "not a calibrated probability".
* Evaluation with no reference events publishes no outcome metric.
* Negative lead times are discarded, not averaged.
* Subgroup records lacking a dimension are reported as `unattributed`, never
  silently attributed to a group.
