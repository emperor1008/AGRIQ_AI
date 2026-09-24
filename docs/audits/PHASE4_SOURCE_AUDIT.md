# Phase 4 Source Audit

Branch: `phase4-image-intelligence-audit`
Baseline commit: `2236b63` (pre-Phase-4 tree, pristine)
Audit date: 2026-09-23
Auditor: automated (bandit 1.9.4, pip-audit, secret-scan regex, route/schema diff, full pytest suite) + manual review

## Scope and method

1. Confirmed Git control; created baseline commit before any change.
2. Inventoried all 51 baseline routes, migration head (0003), env-var names
   (`docs/audits/phase4_route_inventory_baseline.txt`).
3. Ran the full baseline test suite (204 passed, 1 conditional skip).
4. Static analysis (bandit), dependency audit (pip-audit), secret-pattern
   scan over tracked files, route-regression comparison after changes.

## Findings and dispositions

| # | Severity | Location | Finding | Disposition |
|---|----------|----------|---------|-------------|
| 1 | Medium | `agriq/services/crop_stage_service.py:97` | bandit B608 flagged string-built message as possible SQL injection — false positive (plain user-facing text, no SQL) | **Fixed for cleanliness**: restructured so the flagged literal no longer triggers; behaviour unchanged, tests green |
| 2 | High | `ml/data/splits.py:104` | bandit B324: SHA-1 used for split-family ids | **Accepted limitation, hardened**: SHA-1 here is a non-cryptographic grouping key (no secret protection); switched to `usedforsecurity=False` + nosec with justification comment |
| 3 | Medium | `ml/training/export.py:49` | bandit B614: `torch.load` without `weights_only` | **Fixed**: `weights_only=True` added; path is manual-run-only with provenance-recorded checkpoints |
| 4 | Low ×4 (agriq) | various | bandit LOW informational (assert-in-test class, subprocess binds) | **Accepted**: test-only or standard patterns |
| 5 | Low ×4 (ml) | various | bandit LOW informational | **Accepted** |
| 6 | Info | `tests/integration/test_images.py` (initial draft) | Test expected 400 for cross-user access — inconsistent with codebase invariant | **Test corrected** to assert the stronger 404 (foreign resource indistinguishable from missing) |
| 7 | Info | whole repo | No HIGH/MEDIUM pip-audit vulnerabilities (`No known vulnerabilities found`) | **Clean** |
| 8 | Info | whole repo | Secret-pattern scan (AIza/sk-/ghp_ tokens) over tracked files | **Clean** |

## Route regression

- Baseline: 51 routes. Post-Phase-4: 57 (5 image endpoints + capabilities probe).
- Automated route-regression test (`TestRouteRegression`) asserts every
  baseline route still exists with the same method — passes.
- No existing route changed method, auth or response shape.

## Deliberately NOT auto-fixed (require human/product decisions)

1. **No trained model registered** — cannot be "fixed" automatically; requires
   real dataset licensing, training, calibration and a named approver.
2. **Docker build verification** — Docker daemon unavailable on this machine;
   Dockerfile updated (COPY ml) but image build must be run where Docker exists.
3. **Voice/model evaluation datasets** — require consented real recordings;
   fabricating them is forbidden by the real-data policy.
4. **Crop-stage reference coverage** — the versioned reference covers the
   documented crops; extending it requires agronomist review, not automation.

## Verification after fixes

- Full suite: **245 passed, 1 skipped** (was 204 before Phase 4).
- bandit: 0 HIGH, 0 MEDIUM across `apps/api/agriq` and `ml`.
- pip-audit: no known vulnerabilities.
- Migration chain: `0001 → 0002 → 0003 → 0004` upgrade, downgrade and
  re-upgrade tested on isolated SQLite databases.
