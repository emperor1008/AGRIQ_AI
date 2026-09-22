# AGRIQ AI — Technical Architecture (restructured)

This document reflects the **post-refactor** architecture (application
factory + blueprints + layered services). The original monolith analysis
remains valid for context; see `docs/PRD.md` for product scope.

## Architecture decision

Flask 3 is retained. The single 2,400-line `backend/app.py` has been
converted into an application factory plus Blueprints with explicit layers,
preserving every legacy route and the exact UI.

## Layered structure

```text
apps/api/agriq/
├── app_factory.py        # create_app(): config → extensions → blueprints → db
├── extensions.py         # singletons: db (SQLAlchemy), limiter (flask-limiter)
├── core/                 # config, security, logging, exceptions, constants, text, time
├── api/                  # HTTP-only blueprints (auth, dashboard, assistant, weather, health, errors)
├── schemas/              # request parsing/validation DTOs
├── services/             # orchestration (farm/student intelligence, LeafScan, weather advisory, assistant, auth)
├── domain/               # catalogs (crops/districts/diseases/pests/soils/education) + risk engine
├── integrations/         # provider adapters (open_meteo, gemini, agmarknet, openstreetmap)
├── models/               # SQLAlchemy models (users)
├── repositories/         # DB query layer (user_repository)
└── templates/            # base + auth/ + dashboard/ + components/
apps/web/static/          # css/ (6 modules) + js/ (8 modules) + images/ + manifest + sw.js
```

## Module responsibilities (enforced)

| Layer | Responsibility | Forbidden |
|---|---|---|
| `api/` (routes) | Parse request, call service, render/return response | provider calls, image processing, risk math, catalogs |
| `services/` | Coordinate domain + integrations, return structured dicts | HTTP request parsing, template logic |
| `integrations/` | Provider-specific HTTP, parsing, error typing | business rules, user-facing wording |
| `domain/` | Curated reference data + transparent rule logic | I/O of any kind |
| `schemas/` | Normalise/limit/validate external input | provider access |
| `models/` | Table definitions only | routing, provider calls |
| `repositories/` | All DB reads/writes | request handling |

## Request flow examples

### Farmer analysis (`POST /dashboard`)

```text
Browser form (multipart: crop, district, stage, condition, leaf_photo, csrf_token)
  → api/dashboard.py        parse via schemas/farmer.py, session + CSRF checks
  → services/farm_intelligence.analyze_farm()
       ├─ domain/catalogs/crops.resolve_crop()            crop record
       ├─ integrations/weather/open_meteo.get_weather()   live or labelled offline model
       ├─ services/leaf_analysis.safe_analyze()           Pillow screening (validate → analyze)
       ├─ domain/risk/scoring.component_scores()          named, explainable components
       ├─ domain/risk/explanations                        EN + Odia reasons
       ├─ domain/risk/recommendations                     plan, advisories, treatment console
       ├─ services/weather_advisory                       console + 7-day risk outlook
       └─ services/farm_intelligence.make_map_data()      30-district Leaflet circles
  → templates/dashboard/index.html renders the analysis payload
```

### Assistant question (`POST /ask-ai`)

```text
JSON {question, context} + X-CSRF-Token header
  → api/assistant.py        schema parse, CSRF (authenticated sessions), rate limit
  → services/assistant_orchestrator.ask()
       ├─ integrations/ai/gemini.generate_answer()   ONLY when GEMINI_API_KEY set
       └─ (fallback) transparent farmer/student knowledge engine
  → {answer, ok, source: "gemini" | "knowledge_engine"}
```

### Live weather refresh (`GET /api/live-weather`)

```text
Query params (district, crop, stage, condition) — allowlist-normalised
  → api/weather.py
  → integrations/weather/open_meteo.get_weather()  (hour-cached)
       ├─ provider 2xx  → live=True, badge "LIVE SYNC"
       └─ any failure   → offline seasonal model, live=False, badge "OFFLINE FALLBACK"
  → services/weather_advisory.build_weather_console() + forecast_for()
  → JSON {weather_console, risk_forecast}
```

## Extension singletons and rate limits

`flask-limiter` is bound in `app_factory.create_app` with per-route limits
from `03_SECURITY_AND_ACCESS.md`: login 8/min, assistant 12/min, analysis
20/min, weather 30/min. Storage is `memory://` locally and **must** be
Redis in production (`ProductionConfig` refuses `memory://`).

## Data provenance rules

- Every external-data payload carries provider, timestamp, freshness
  (`live`) metadata — see `docs/DATA_PROVENANCE.md`.
- Provider failure returns a typed unavailable state
  (`domain/common.ProviderUnavailable`, `core/exceptions`).
- Deterministic fallbacks are labelled ("OFFLINE FALLBACK") and never
  presented as live weather, prices, map risk or Gemini output.

## Database

- Local development: SQLite (`DATABASE_URL=sqlite:///agriq.db`).
- Production: PostgreSQL **required**; `ProductionConfig` refuses SQLite.
- Initial entity: `users` (id, contact, password_hash, created_at).
- Future entities (farmer_profiles, farms, fields, crop_cycles,
  observations, risk_assessments, market_prices, conversations, messages)
  follow `docs/TECHNICAL_ARCHITECTURE.md` initial schema; migrations live
  in `apps/api/migrations/` (DATA-01).

## Route compatibility

Unchanged: `/`, `/login`, `/choose`, `/choose-mode`, `/dashboard`,
`/ask-ai`, `/api/live-weather`, `/logout`, `/healthz`.
`/logout` now prefers POST + CSRF; plain GET remains for the side-rail link.
