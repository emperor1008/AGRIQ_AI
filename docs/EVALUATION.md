# Evaluation (Phase 2)

## Status: NOT YET VALIDATED

AGRIQ displays **no accuracy percentage, benchmark score or quality claim**
anywhere in the product or documentation, because no reviewed evaluation
dataset exists yet. This file defines the process that must be completed
before any such number may be shown.

## Evaluation dataset policy

Only real, reviewable data may enter the evaluation set:

- Agronomist-reviewed questions with agreed expected evidence and safe
  actions
- Anonymised, consented farmer questions (only where consent covers
  evaluation use)
- Official advisory scenarios from the approved sources
- Real provider responses captured with timestamps
- Human-reviewed expected evidence sets

Never: synthetic agronomy articles, LLM-generated Q&A pairs, fabricated
scores, or any test fixture from `apps/api/tests/`.

## Required dimensions

Each must reach a documented pass threshold agreed with an agronomist
before any public claim:

1. Groundedness — answers contain only verifiable claims
2. Citation correctness — every citation exists in the registry and
   supports the statement
3. Context personalisation — answer references the caller's real context
4. Safety — zero unblocked dosage/mixing/exposure violations
5. Actionability — one clear action per advisory answer
6. Multilingual quality — EN/HI/OR reviewed by real speakers (no dialect
   claims until then)
7. Unsupported-claim rate — target zero tolerance
8. Cross-user privacy — zero leakage across accounts
9. Provider-failure handling — unavailable states surfaced honestly

## Reporting rules

- Results are reported with dataset version, reviewer names, dates and the
  copilot prompt/knowledge versions evaluated.
- A failing dimension blocks any public quality claim.
- Evaluation artefacts live outside the production database and are never
  served by the app.
