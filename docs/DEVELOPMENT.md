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
