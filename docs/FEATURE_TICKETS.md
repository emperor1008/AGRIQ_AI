# AGRIQ AI — Feature Ticket List

## Architecture release: mandatory build order

| ID | Ticket | Priority | Depends on | Acceptance criteria |
|---|---|---|---|---|
| ARC-01 | Add application factory | Must-have | None | `create_app()` creates the application; existing routes work |
| ARC-02 | Create Flask Blueprints | Must-have | ARC-01 | Auth, dashboard and API routes are separate modules; URLs unchanged |
| ARC-03 | Separate configuration/extensions | Must-have | ARC-01 | Config, DB and limiter not defined in route modules |
| ARC-04 | Extract domain catalogues | Must-have | ARC-01 | District/crop/student reference data leaves `app.py`; behaviour unchanged |
| ARC-05 | Extract weather integration | Must-have | ARC-02 | Open-Meteo code lives only in `integrations/weather.py` |
| ARC-06 | Extract market/Gemini integrations | Must-have | ARC-02 | Provider-specific HTTP calls live only in `integrations/` |
| ARC-07 | Extract LeafScan and farm intelligence | Must-have | ARC-04 | Image/risk logic lives in service modules; no diagnosis claim introduced |
| ARC-08 | Move static assets safely | Must-have | ARC-02 | Existing UI is visually unchanged; manifest/service worker work |
| ARC-09 | Add tests by layer | Must-have | ARC-01–08 | Unit, integration and security tests pass |
| ARC-10 | Update deployment/docs | Must-have | ARC-01–09 | README, Docker, CI, validation and architecture docs match new paths |

## Production data release: after architecture

| ID | Ticket | Priority | Depends on | Acceptance criteria |
|---|---|---|---|---|
| DATA-01 | Add PostgreSQL migrations | Must-have | ARC-03 | Migration can create users and future farm domain tables cleanly |
| DATA-02 | Farmer/farm/field profile | Must-have | DATA-01 | Authenticated user can create and view only their own records |
| DATA-03 | Crop-cycle tracking | Must-have | DATA-02 | Crop, date, stage, soil and field are persisted and reused in analysis |
| DATA-04 | Provenance service | Must-have | ARC-05/06 | All external results include provider, timestamp and freshness |
| DATA-05 | Historical mandi ingestion | Should-have | DATA-01 | Official records stored without invented values and with source metadata |
| AI-01 | Assistant orchestration | Must-have | DATA-02–04 | Assistant receives verified farmer context and cites source cards |
| AI-02 | Voice Odia/Hindi/English | Should-have | AI-01 | Audio transcription shows confidence and user can correct transcript |
| AI-03 | Validated image model | Should-have | DATA-02 | Supported crops return calibrated top results or abstain; model card exists |
| RISK-01 | Scheduled multi-risk alerts | Should-have | DATA-03/04 | Alerts show threat, severity, reasons, action, data freshness |
| MARKET-01 | Price forecast/backtest | Should-have | DATA-05 | Forecast beats baseline in documented backtest or is not displayed |
| MARKET-02 | Net-market comparison | Nice-to-have | MARKET-01 | Shows price, transport cost and estimated net return transparently |

## Definition of done for every ticket

- No UI regression unless the ticket explicitly requests UI change.
- Input validation and safe error state included.
- Tests added/updated.
- No secret or dummy production data committed.
- README/API/architecture documentation updated when behaviour changes.
- Manual mobile and desktop verification completed.

