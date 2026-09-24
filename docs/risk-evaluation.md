# Risk Evaluation (Phase 5)

**Status: evaluation unavailable — insufficient validated data.**

No precision, recall, F1, false-alert rate, missed-event rate, calibration or
warning-lead-time figures are displayed anywhere in AGRIQ AI, because no
validated evaluation dataset exists yet. Fabricating any of these numbers is
prohibited by the project's real-data policy.

## What exists today

- **Evaluation infrastructure**: the persistence layer keeps every assessment
  append-only (`risk_assessments.record_status`, `run_group`), so future
  outcomes can be joined against the exact evidence and rule version that
  produced them (`rule_version`, `model_version` stored per row).
- **Farmer action signals**: `farmer_actions` records planned / completed /
  skipped / needs-help responses with farmer notes. These are operational
  feedback, **not** ground-truth labels, and are never counted as evaluation
  results without documented review and consent.
- **Versioned rules**: `agriq-risk-rules-v1` pins every threshold, so any
  historical assessment remains reproducible.

## Required evaluation protocol (before any metric is published)

1. **Reference events** — verified records of actual heavy-rain events,
   heat episodes, dry spells, waterlogging and (where available) confirmed
   disease pressure, with dates and districts, from official sources
   (IMD records, agriculture department reports).
2. **Temporal split** — past periods for calibration, later periods for
   testing; no random splitting that leaks future information.
3. **Blind review** — agronomist review of sampled assessments for
   groundedness (does the evidence support the status?) and actionability.
4. **Metrics to compute** — precision/recall/F1 per risk type at each status
   band, false-alert and missed-event rates, probability calibration
   (reliability curve), and warning lead time vs event onset.
5. **Separate reporting** — per risk type, per crop (rice/tomato), per
   district, and per data-freshness band.

Until that protocol has been executed with real reviewed data, the only
correct public statement is:

> "Risk screening evaluation is in progress; metrics are not yet available."
