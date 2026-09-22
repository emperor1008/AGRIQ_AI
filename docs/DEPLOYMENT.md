# AGRIQ AI — Deployment

Detailed runbook: `infrastructure/deployment/README.md`.

## Topology

```text
Browser ── HTTPS ──▶ nginx (static + proxy)
                        │
                        ▼
                 Gunicorn (wsgi:app) ──▶ PostgreSQL (production required)
                        │             ──▶ Redis (rate limits, production required)
                        ├──▶ Open-Meteo   (weather; labelled live/offline)
                        ├──▶ Gemini       (optional assistant upgrade)
                        └──▶ data.gov.in  (optional AGMARKNET mandi prices)
```

## Quick start (Docker Compose)

```bash
cd infrastructure/docker
export AGRIQ_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export POSTGRES_PASSWORD="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
docker compose up -d --build
curl -f http://localhost/healthz
```

## Production hard rules

1. `AGRIQ_ENV=production` — activates `ProductionConfig` guard rails
   (refuses SQLite, refuses in-memory limiter, requires secret key).
2. `AGRIQ_COOKIE_SECURE=1` and `AGRIQ_ENABLE_HSTS=1` behind HTTPS only.
3. Secrets only via environment/deployment secrets — never in code.
4. `client_max_body_size 6m` at the proxy (uploads capped at 5 MiB).
5. Health check: `GET /healthz` must return `{"status": "ok"}`.

## Zero-downtime notes

- App is stateless apart from PostgreSQL/Redis; scale API replicas freely.
- Rate limits are shared via Redis so replicas enforce one budget.
- Static assets are immutable-cached (`nginx.conf`); bump `CACHE_NAME` in
  `apps/web/static/sw.js` when shipping frontend changes.

## Post-deploy verification

1. `python scripts/validate_project.py` in CI/build.
2. `pytest apps/api/tests` green.
3. Manual smoke: login → choose mode → farmer analysis → assistant → logout.
4. Mobile viewport + PWA install checks.
5. Provider provenance labels visible: weather `LIVE SYNC`/`OFFLINE
   FALLBACK`, market unavailable state (no fabricated prices), assistant
   source label (`gemini`/`knowledge_engine`).

## Pre-launch security gates (from docs/SECURITY_AND_ACCESS.md)

- Email/phone verification and recovery flows.
- Dependency scan, SAST, secret scan and manual OWASP review
  (workflows provided in `.github/workflows/security.yml`).
- Privacy notice, consent flow, retention/deletion, incident response.
- Load, backup/restore and DB access-control tests.
