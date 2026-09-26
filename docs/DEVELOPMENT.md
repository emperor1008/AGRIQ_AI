# AGRIQ AI — Development Guide

## Prerequisites

- Python 3.11+ (3.12 recommended)
- pip
- Optional: Gemini API key, data.gov.in API key (see `.env.example`)

## Setup

```bash
# 1. Virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# 2. Dependencies
pip install -r apps/api/requirements.txt

# 3. Configuration
cp .env.example .env        # then edit AGRIQ_SECRET_KEY etc.

# 4. Environment sanity check
python scripts/check_environment.py
```

## Run

```bash
python run.py          # http://127.0.0.1:5000
```

`run.py` adds `apps/api` to `sys.path` and calls `create_app()` from
`apps/api/agriq/__init__.py`. `apps/api/app.py` (a two-line shim) and
`apps/api/wsgi.py` are the compatibility/production targets.

## Database migrations

Schema changes ship as Alembic revisions (`apps/api/migrations/versions/`).
SQLite dev databases created by `create_all()` at boot do **not** gain new
columns automatically, so after pulling a revision that adds columns run:

```bash
cd apps/api && python run_migrations.py upgrade    # apply pending revisions
python run_migrations.py current                   # confirm the head revision
```

Migrations are additive and idempotent (existing tables are altered only when a
column is genuinely missing) and never insert seed or demo rows. Production
PostgreSQL must be migrated the same way before the new code is deployed.

## Test

```bash
python scripts/run_tests.py            # pytest via wrapper
# or directly:
cd apps/api && python -m pytest tests -v
```

Test layout:

```text
apps/api/tests/
├── conftest.py           # app/client/csrf/auth fixtures
├── unit/                 # factory, domain, integrations, LeafScan
├── integration/          # route flows (auth, dashboards, APIs)
└── security/             # CSRF, headers, uploads, no-fabrication, secrets
```

## Validation

```bash
python scripts/validate_project.py
```
Checks required files, Python syntax of every module, absence of
secret-like literals, CSS module integrity and that `create_app()` exposes
all legacy routes.

## Code layout conventions

- Routes stay thin: parse → call service → respond. No provider calls,
  risk math or reference data in `api/`.
- Add reference data to `domain/catalogs/`, provider code to
  `integrations/`, orchestration to `services/`.
- Absolute imports inside the package (`from agriq.core... import ...`).
- Every external result carries provenance; provider failure → typed
  unavailable state (never fabricated data).

## Risk evaluation (offline)

```bash
cd apps/api
python -m agriq.cli.evaluate_risk --events /path/to/reference_events.json
```

Operator tool, never a route. Without a real reference-event dataset it prints
an honest `insufficient_data` report. See `docs/risk-evaluation.md`.

## Market intelligence (Phase 6)

Rules, methodology and honest-state contracts live in `docs/market-engine.md`,
`docs/market-data-sources.md`, `docs/market-api.md` and
`docs/market-intelligence.md`. The short version for contributors:

- Prices, trend, volatility and forecasts are built only from official AGMARKNET
  rows the deployment actually stored; nothing is backfilled, and a thin history
  is reported as thin (`insufficient_data`), never padded.
- `MARKET_SNAPSHOT_TTL_SECONDS` bounds the per-app provider cache
  (`services/market_intelligence._cache`); failures are cached too, so an outage
  cannot become a request storm.
- Domain engines live in `domain/market/` and stay pure (no Flask, no DB); only
  `services/market_intelligence.py` touches the app, DB, provider and Phase 5
  risk rows.
- Tests seed `MarketPriceRecord` rows shaped like documented AGMARKNET fields as
  explicit in-memory fixtures (`tests/integration/test_market_intel.py`); no
  market value is ever shipped as data.
- Costs are the farmer's own figures and follow one rule everywhere: a **blank**
  field means unknown (the net value is withheld as `NET_VALUE_INCOMPLETE`), an
  explicit **`0`** is a known zero, and a supplied freight total wins over
  rate × distance. The dashboard panel ships those inputs empty and omits blank
  ones from the request rather than defaulting them.

## Environment variables

See `.env.example` for the full contract. Production additionally requires
PostgreSQL + Redis and is guarded by `core/config.ProductionConfig`
(which refuses SQLite / in-memory limiter).

## Project validation before every push

```bash
python scripts/validate_project.py && python scripts/run_tests.py
```

CI (`.github/workflows/ci.yml`) runs validation + tests on Python 3.11/3.12;
`security.yml` runs bandit, pip-audit and a secret scan.
