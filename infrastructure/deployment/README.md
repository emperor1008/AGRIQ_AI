# AGRIQ AI — Deployment

## Requirements (production hard rules)

| Requirement | Why |
|---|---|
| PostgreSQL (`DATABASE_URL`) | Farmer data persistence; SQLite is dev-only |
| Redis (`RATELIMIT_STORAGE_URI`) | Shared rate limits across workers |
| Long random `AGRIQ_SECRET_KEY` | Session signing |
| HTTPS termination | `AGRIQ_COOKIE_SECURE=1`, `AGRIQ_ENABLE_HSTS=1` |
| Secrets via environment | No keys ever in source or browser JS |

## Docker Compose (recommended)

```bash
cd infrastructure/docker
export AGRIQ_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export POSTGRES_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
# optional providers:
export GEMINI_API_KEY=...
export DATA_GOV_IN_API_KEY=...

docker compose up -d --build
curl http://localhost/healthz
```

## Manual Gunicorn

```bash
cd apps/api
export AGRIQ_ENV=production
export AGRIQ_SECRET_KEY=...
export DATABASE_URL=postgresql://...
export RATELIMIT_STORAGE_URI=redis://...
gunicorn --bind 0.0.0.0:8000 --workers 2 --threads 4 wsgi:app
```

## Release checklist

1. `python scripts/validate_project.py` passes.
2. `pytest apps/api/tests` passes.
3. `GET /healthz` returns `{"status": "ok"}`.
4. Login → choose → farmer analysis → assistant → logout smoke-tested.
5. Mobile layout + PWA assets verified.
6. Provider states verified: weather live/fallback label, Gemini unavailable → 503-ish safe message, market unavailable label (no fabricated values).
