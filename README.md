# AGRIQ AI 🌾

**Smart Agriculture, Brighter Tomorrows** — a mobile-first agriculture
intelligence platform for Odisha farmers and agriculture students, built on
a professional, scalable frontend/backend architecture with a persisted
farmer-data foundation (Phase 1), a personalised Farm Copilot (Phase 2), a
multilingual voice interface (Phase 3) and validated crop-image
intelligence foundations (Phase 4).

- **Farmer Mode** — real accounts, farmer profile, farms & fields, soil
  records, crop cycles with transparent stage calculation, field timeline,
  live Open-Meteo weather for registered field coordinates, official
  AGMARKNET mandi records, explainable crop-risk engine, LeafScan image
  screening, treatment & advisory console, English + Odia advisories, and
  the **Farm Copilot**: a context-aware, evidence-backed assistant with
  conversation memory, provenance-labelled answers, safety guardrails,
  multilingual output (English/Hindi/Odia), low-bandwidth mode and
  recommendation feedback tracking.
- **Student/Research Mode** — syllabus notes, research plans, pest/disease
  libraries, MCQs, viva prep, calculators, career direction, AI assistant.

## Phase 4 — Crop-Image Intelligence (foundations)

The image pipeline (`/api/v1/crop-images/*`, docs/IMAGE_INTELLIGENCE.md) is
built end-to-end with a fail-closed contract: decoded-format verification,
quality gate with retake guidance, abstention policy and registry-gated
model loading. **No model is approved for production yet** — the feature
honestly reports "Image analysis is not currently available." until a real
dataset-licensed, calibrated, evaluated model is registered by a named
approver. See `ml/README.md` for the full pipeline.

## Phase 2 — Personalised Farm Copilot
The copilot (`POST /api/v1/copilot/messages`, docs/FARM_COPILOT.md) grounds
every answer in the authenticated farmer's verified context plus approved
agricultural knowledge:

- **Orchestration pipeline** — ownership checks → farmer context →
  deterministic intent routing (EN/HI/OR) → tool calls (weather/market) →
  retrieval over **approved sources only** → freshness validation → safety
  guardrails → evidence package → bounded Gemini prompt → validation →
  persistence (conversation, evidence, `assistant_runs` provenance,
  structured recommendations).
- **Documented confidence** (`copilot-confidence-v1`) — explicit weighted
  formula over context completeness, weather freshness, knowledge relevance,
  direct observations, conflicts and missing inputs. Low confidence never
  auto-persists an action; it escalates.
- **Safety guardrails in code** — no exact pesticide/fertiliser dosage
  without approved evidence + confirmed field area, no chemical mixing
  advice, no spraying guidance under missing/unsafe weather, immediate
  handover on exposure emergencies, expert escalation on severe symptoms,
  unsupported conditions, conflicts and low confidence.
- **Knowledge base** — versioned source registry with organisation
  allowlist (ICAR / Govt. of Odisha / OUAT / KVK), ingestion CLI with
  checksums and human review gate, lexical retrieval with relevance
  threshold. No fake embeddings; no LLM-invented citations.
- **Feedback loop** — `POST /api/v1/recommendations/{id}/feedback` records
  completed/skipped/needs-help plus outcomes; owner-checked; no feedback is
  never interpreted as success.
- **Honest states** — Gemini unavailable → "The AI assistant is temporarily
  unavailable."; no approved passage → "verified guidance is unavailable";
  no official record → "Official matching records unavailable." Evaluation
  is **not yet validated** (docs/EVALUATION.md) and no accuracy is claimed.

## Phase 1 — Shared Farmer Intelligence Foundation

All future modules (Crop Risk Intelligence, Farm-to-Market Optimizer) build
on the same persisted, ownership-scoped data:

- **13 tables** via SQLAlchemy + Alembic (`run_migrations.py`):
  users, farmer_profiles, farms, fields, soil_tests, crop_cycles,
  field_observations, weather_snapshots, market_price_records,
  conversations, messages, recommendations, farmer_actions.
- **Real-data policy** — no dummy/mock/fabricated values in production.
  Weather is live-or-unavailable (the offline seasonal model was REMOVED);
  mandi prices are official-records-or-unavailable; unanalysed map
  districts show "Awaiting verified analysis."; missing soil values stay
  unknown; without Gemini the farmer assistant reports an explicit
  unavailable state. See `docs/DATA_PROVENANCE.md`.
- **Shared Farmer Context** — one verified, ownership-checked structure
  (`GET /api/farmer-context`) feeding the dashboard, the assistant and
  every future module.
- **Ownership isolation** — every repository lookup joins back to the
  authenticated farmer; another farmer's record is indistinguishable from
  a missing one (404), proven by dedicated two-user tests.

## What changed in this refactor

The former 2,400-line `backend/app.py` monolith is now a layered Flask
application factory. **All routes, visuals, colour palette and behaviour
are preserved** — the CSS was split mechanically (recombines
byte-identically) and the inline JS was extracted into modules.

### Architecture at a glance

```text
Request → Blueprint (HTTP only) → Service (orchestration)
       → Domain (catalogs + risk rules) / Integration (providers)
       → Response with provenance labels
```

| Layer | Location | Rule |
|---|---|---|
| Routes | `apps/api/agriq/api/` | HTTP only — no provider calls, risk math or data blobs |
| Services | `apps/api/agriq/services/` | Orchestration, structured results |
| Domain | `apps/api/agriq/domain/` | Curated catalogs + explainable risk engine |
| Integrations | `apps/api/agriq/integrations/` | Open-Meteo, Gemini, AGMARKNET, OSM |
| Core | `apps/api/agriq/core/` | Config, security, logging, exceptions |
| Frontend | `apps/web/static/` | 6 CSS modules, 8 JS modules, PWA assets |

### Old-file → new-file migration table

| Old (monolith) | New (restructured) |
|---|---|
| `backend/app.py` — Flask setup, secret key | `apps/api/agriq/app_factory.py` + `apps/api/agriq/core/config.py` |
| `backend/app.py` — session helpers, password logic | `apps/api/agriq/core/security.py`, `apps/api/agriq/services/authentication.py` |
| `backend/app.py` — routes (`/`, `/login`, `/choose`, `/choose-mode`, `/dashboard`, `/ask-ai`, `/api/live-weather`, `/logout`) | `apps/api/agriq/api/auth.py`, `api/dashboard.py`, `api/assistant.py`, `api/weather.py`, `api/errors.py` |
| `backend/app.py` — `districts`, `DISTRICT_PROFILES`, zones | `apps/api/agriq/domain/catalogs/districts.py` |
| `backend/app.py` — `CROPS`, `MARKET_BASELINE`, stages | `apps/api/agriq/domain/catalogs/crops.py` |
| `backend/app.py` — `PEST_LIBRARY` | `apps/api/agriq/domain/catalogs/pests.py` |
| `backend/app.py` — `DISEASE_LIBRARY` | `apps/api/agriq/domain/catalogs/diseases.py` |
| `backend/app.py` — `SOIL_LIBRARY` | `apps/api/agriq/domain/catalogs/soils.py` |
| `backend/app.py` — student areas/levels/methods/animals/semester/career banks | `apps/api/agriq/domain/catalogs/education.py` |
| `backend/app.py` — risk scoring/health/productivity | `apps/api/agriq/domain/risk/scoring.py` |
| `backend/app.py` — reasons + EN/Odia advisories | `apps/api/agriq/domain/risk/explanations.py` |
| `backend/app.py` — action plan, farm twin, treatment console | `apps/api/agriq/domain/risk/recommendations.py` |
| `backend/app.py` — weather code map, `format_weather_time` | `apps/api/agriq/core/constants.py`, `core/time.py` |
| `backend/app.py` — `deterministic_weather`, `fetch_weather`, forecast | `apps/api/agriq/integrations/weather/open_meteo.py` |
| `backend/app.py` — weather console builder | `apps/api/agriq/services/weather_advisory.py` |
| `backend/app.py` — `analyze_leaf_image` (Pillow) | `apps/api/agriq/services/leaf_analysis.py` |
| `backend/app.py` — `analyze_farm`, map data, market/profit bands | `apps/api/agriq/services/farm_intelligence.py` |
| `backend/app.py` — student result builders + dropdown sections | `apps/api/agriq/services/student_intelligence.py` |
| `backend/app.py` — `generate_farmer_ai_answer`, `generate_student_ai_answer` | `apps/api/agriq/services/assistant_orchestrator.py` |
| `backend/services/llm.py` (Gemini) | `apps/api/agriq/integrations/ai/gemini.py` |
| — (new) | `apps/api/agriq/integrations/market/agmarknet.py` (fails closed; no fabricated prices) |
| — (new) | `apps/api/agriq/integrations/maps/openstreetmap.py` |
| — (new) | `apps/api/agriq/models/user.py`, `repositories/user_repository.py` |
| `backend/templates/index.html` (875 lines + inline JS) | `apps/api/agriq/templates/base.html`, `auth/login.html`, `auth/choose.html`, `dashboard/index.html`, `components/_macros.html` |
| `backend/static/style.css` (2,184 lines) | `apps/web/static/css/{tokens,base,components,dashboard,animations,responsive}.css` (byte-identical recombination) |
| inline `<script>` block | `apps/web/static/js/{app,api-client,assistant,dashboard,map,weather,leafscan,pwa}.js` |
| — (implicit PWA) | `apps/web/static/manifest.json`, `apps/web/static/sw.js`, `apps/web/static/images/agriq-ai-logo.png` |
| `Dockerfile` (root, old paths) | `apps/api/Dockerfile` + `docker-compose.yml` + `infrastructure/docker/docker-compose.yml` + `infrastructure/nginx/nginx.conf` |
| `scripts/validate_project.py` (old paths) | rewritten for new structure + `scripts/check_environment.py`, `scripts/run_tests.py` |
| `docs/HACKATHON_CHECKLIST.md` | superseded by `docs/{PRD,TECHNICAL_ARCHITECTURE,SECURITY_AND_ACCESS,FRONTEND_SPECIFICATION,FEATURE_TICKETS,API,DEVELOPMENT,DEPLOYMENT,DATA_PROVENANCE}.md` |

## Data sources & integrity rules

| Capability | Source | Key required? | On failure |
|---|---|---|---|
| Weather + 7-day forecast | Open-Meteo | No | Labelled `OFFLINE FALLBACK` (never shown as live) |
| Map tiles | OpenStreetMap/Leaflet | No | Tiles simply don't render |
| Generative AI | Gemini REST API | Optional | Built-in knowledge engine, labelled `knowledge_engine` |
| Leaf image analysis | Pillow colour heuristic | No | Honest "not analysed" state |
| Mandi prices | AGMARKNET via data.gov.in | Yes | Explicit unavailable state — **no prices generated** |

AGRIQ never fabricates live weather, market prices, district-risk "ML"
values, Gemini answers or disease diagnoses. LeafScan is a transparent
colour-pattern **screening** aid, not a trained model. See
`docs/DATA_PROVENANCE.md`.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r apps/api/requirements.txt
cp .env.example .env                   # set AGRIQ_SECRET_KEY (and optional keys)

cd apps/api && python run_migrations.py upgrade && cd ../..   # apply schema
python scripts/check_environment.py    # sanity check
python run.py                          # → http://127.0.0.1:5000
```

(SQLite development also auto-creates the schema at boot; the migration
run above is the source of truth and is required for PostgreSQL.)

## Test & validate

```bash
python scripts/validate_project.py          # structure + syntax + routes + secrets
python scripts/run_tests.py                 # full pytest suite (111 tests)
python scripts/run_tests.py unit            # unit tests only
python scripts/run_tests.py integration     # integration tests only
python scripts/run_tests.py security        # security tests only
```

Covered: application factory, health, real-account registration/login,
session protection, CSRF, mode selection, both dashboards, the full
farmer onboarding chain (profile → farm → field → soil → cycle → stage
confirm → observation → context), ownership isolation between two
users, crop-stage calculation, weather success/unavailable + retry,
market unavailable, Gemini configured/unavailable, upload validation,
migration chain (upgrade + downgrade), security headers, PWA assets and
the no-fabrication guarantees.

## Deployment

```bash
docker compose up -d --build                          # simple API container
# or full production topology:
cd infrastructure/docker && docker compose up -d --build
```

Production requires PostgreSQL and Redis (enforced by config), HTTPS with
`AGRIQ_COOKIE_SECURE=1`/`AGRIQ_ENABLE_HSTS=1`, and secrets only via the
environment. See `docs/DEPLOYMENT.md`.

## Project structure

```text
AGRIQ_AI/
├── apps/
│   ├── api/
│   │   ├── agriq/
│   │   │   ├── __init__.py            # create_app re-export
│   │   │   ├── app_factory.py         # create_app() factory
│   │   │   ├── extensions.py          # db, limiter
│   │   │   ├── core/                  # config, security, logging, exceptions, constants, text, time
│   │   │   ├── api/                   # health, auth, dashboard, assistant, weather, errors
│   │   │   ├── models/                # user.py
│   │   │   ├── schemas/               # auth, farmer, assistant, weather, common
│   │   │   ├── repositories/          # user_repository.py
│   │   │   ├── domain/
│   │   │   │   ├── catalogs/          # crops, districts, diseases, pests, soils, education
│   │   │   │   ├── risk/              # scoring, explanations, recommendations, adjustments
│   │   │   │   └── common.py          # provenance wrappers
│   │   │   ├── services/              # authentication, farm_intelligence, student_intelligence,
│   │   │   │                          # leaf_analysis, weather_advisory, assistant_orchestrator
│   │   │   ├── integrations/
│   │   │   │   ├── weather/open_meteo.py
│   │   │   │   ├── ai/gemini.py
│   │   │   │   ├── market/agmarknet.py
│   │   │   │   └── maps/openstreetmap.py
│   │   │   └── templates/             # base.html, auth/, dashboard/, components/
│   │   ├── migrations/                # Alembic-style versioned migrations
│   │   ├── tests/                     # unit/ integration/ security/ + conftest.py
│   │   ├── app.py                     # app = create_app()
│   │   ├── wsgi.py                    # Gunicorn target
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   └── web/
│       ├── static/                    # css/ js/ images/ icons/ manifest.json sw.js
│       └── README.md
├── packages/shared/                   # constants + shared types
├── infrastructure/                    # docker/, nginx/, deployment/
├── scripts/                           # validate_project, check_environment, run_tests
├── docs/                              # PRD, architecture, security, frontend, tickets,
│                                      # data provenance, API, development, deployment
├── .github/workflows/                 # ci.yml, security.yml
├── .env.example
├── docker-compose.yml
├── LICENSE
├── README.md
└── run.py
```

## Security summary

Secure HttpOnly SameSite session cookies (Secure under HTTPS) · CSRF on
all state-changing routes (form field or `X-CSRF-Token`) · POST logout ·
Werkzeug password hashing · rate limits (login 8/min, assistant 12/min,
analysis 20/min, weather 30/min) · input length limits and
district/crop/stage allowlists · upload allowlist (JPEG/PNG/WebP, ≤5 MiB,
safe decode) · CSP + nosniff + `X-Frame-Options: DENY` + referrer policy ·
HSTS behind HTTPS · environment-only secrets · production PostgreSQL +
Redis enforced · safe user-facing error messages · no API keys in source
or browser JS.

Full details: `docs/SECURITY_AND_ACCESS.md`.

## Remaining production limitations

1. **Contact verification** — no OTP/email ownership verification yet.
2. **No farmer profile persistence** — analysis is per-request; the
   users table exists, farm/field/crop-cycle entities arrive with DATA-01..03.
3. **LeafScan** remains a colour-pattern screening aid (AI-03 covers a
   validated model later).
4. **Market feed** requires a data.gov.in key; without it only labelled
   context bands are shown.
5. **Single-language voice** — voice I/O is out of scope for this release.
6. **Weather fallback** is a seasonal statistical model, clearly labelled —
   it is not observed data.
7. **Crop-image model** — pipeline is built but no model is registered as
   approved for production; the feature reports an honest unavailable state
   until a validated model exists (see docs/IMAGE_INTELLIGENCE.md).
8. **Voice/image evaluation** — real evaluation datasets require consented
   field recordings and agronomist review; no accuracy numbers are claimed.

## License

See `LICENSE`.
