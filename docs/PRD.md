# AGRIQ AI — Product Requirements Document

## Product summary

AGRIQ AI is a mobile-first agriculture intelligence platform for Odisha farmers and agriculture students. It provides one premium conversational experience for crop guidance, weather-aware field decisions, transparent visual crop screening, explainable risk intelligence, and verified market information.

## Problem

Farmers often receive generic advice from disconnected tools. They need a simple, local-language system that connects their crop, field condition, weather, observed symptoms, and market situation. Agriculture students also need structured, beginner-friendly learning support.

## Target users

| User | Need | Constraint |
|---|---|---|
| Small and medium farmer in Odisha | Practical crop action, risk explanation, local weather and price context | Low bandwidth, limited digital literacy, Odia/Hindi/English needs |
| Agriculture student | Notes, viva preparation, research planning, calculators | Needs clear, non-fabricated content |
| Agronomist/admin (future) | Review knowledge, models and alerts | Must not access farmer data without authorisation |

## Vision

AGRIQ AI becomes a trusted crop-cycle copilot: it helps a farmer decide what to do today, explains risk early, and later supports profitable market decisions using verified data.

## Current codebase facts

The uploaded project is a Flask prototype with Farmer and Research modes, an Open-Meteo weather integration, OpenStreetMap map tiles, a Gemini adapter, and a Pillow colour-pattern LeafScan. It has no persistent farmer profile/database and its single `backend/app.py` contains most application logic. The legacy prototype contains deterministic fallback logic; it must never be presented as live data in a production release.

## MVP scope

### Must have

- Premium existing UI preserved exactly during architecture refactor.
- Login, workspace selection, Farmer dashboard and Student/Research dashboard.
- Live weather shown only when the weather provider responds; otherwise a clear unavailable state.
- Image upload with transparent **screening** label, not disease diagnosis.
- Explainable farm-risk result based on crop, district, growth stage, field condition, and verified weather.
- Gemini assistant only when configured; never invent a provider answer.
- Verified government mandi integration when configured; otherwise unavailable state.
- Secure sessions, CSRF, rate limits, input validation, upload limits, structured error handling.
- Professional modular code structure, tests, documentation, CI and deployment configuration.

### Should have after architecture is stable

- Persisted farmer profile, farm, field, soil test, crop cycle and observations.
- Odia/Hindi/English voice input and output.
- Historical mandi ingestion and forecast backtesting.
- Offline queue for observations and photos.
- Agronomist-reviewed knowledge citations.

### Nice to have later

- Crop-choice engine, logistics optimiser, demand forecast, alert notifications, cooperative/admin workspace.

## Out of scope for version one

- Pesticide dosage or legal prescription.
- Claiming a Pillow colour heuristic is trained disease AI.
- Yield, profit or treatment-effect predictions without measured field data and evaluation.
- National rollout across every crop, language and mandi.
- Fake demo values disguised as live weather, price, maps or AI results.

## Core user flows

### Farmer analysis

1. User signs in and chooses Farmer mode.
2. User selects crop, Odisha district, crop stage and field condition.
3. User optionally uploads a clear leaf/crop image.
4. AGRIQ retrieves live weather.
5. AGRIQ shows an explainable risk score, reasons, forecast, safety-first actions and provider timestamps.
6. User asks a follow-up question in the same assistant panel.
7. If data is unavailable, AGRIQ says so instead of creating an answer/value.

### Student/research support

1. User selects Student/Research mode.
2. User selects learning area, topic, crop and purpose.
3. AGRIQ generates structured learning material, research-plan support, calculators and viva content.
4. The user can ask follow-up questions using the configured assistant.

## Success metrics

- 100% of live-data cards show source and last-updated information.
- 0 fabricated live weather, market-price or disease-diagnosis claims.
- ≥95% successful page/API responses under normal configured-provider conditions.
- ≥80% of farmer test users can complete one field analysis unaided.
- ≥80% of users understand the reason behind a risk alert in usability testing.
- 100% critical routes covered by automated security and integration tests.

## Product principles

1. Explain why, not only what.
2. Prefer an honest unavailable state to invented data.
3. Preserve farmer simplicity even when backend intelligence grows.
4. Treat health and crop-risk suggestions as advisory, not a replacement for local experts.

