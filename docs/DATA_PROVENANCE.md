# AGRIQ AI — Data Provenance Register (Phase 1 + Phase 2)

Every value displayed or stored by AGRIQ AI comes from one of the sources
below. When a source cannot be reached, the UI shows
**"Verified data is currently unavailable."** — generated values are never
substituted, in any module, under any failure mode.

Last reviewed: 2026-09-22.

## Source register

| # | Feature | Provider | Endpoint / resource | Licence / usage note | Fields used | Retrieval method | Cache policy | Failure behaviour | Data class | Last reviewed |
|---|---------|----------|---------------------|----------------------|-------------|------------------|--------------|-------------------|------------|---------------|
| 1 | Live weather (current + hourly + 7-day forecast) | Open-Meteo | `https://api.open-meteo.com/v1/forecast` | Open-Meteo free API, non-commercial use, attribution required | temperature_2m, relative_humidity_2m, precipitation, rain, weather_code, wind_speed_10m (+ hourly/daily series) | Server-side GET, 8 s timeout, max 1 safe retry (no retry on 4xx) | In-memory TTL 30 min per coordinate; snapshots persisted per field, de-duplicated by response hash | Explicit UNAVAILABLE state; last stored snapshot may be shown labelled `cached/stale` — no values invented | Observation (current) + forecast (hourly/daily) | 2026-09-22 |
| 2 | Mandi prices | AGMARKNET via data.gov.in (OGD platform) | Resource `9ef84268-d588-465a-a308-a864a43d0070` (configurable via `DATA_GOV_IN_MARKET_RESOURCE_ID`) | Government of India Open Data; usage per OGD terms; requires `DATA_GOV_IN_API_KEY` | state, district, market, commodity, variety, arrival_date, min/max/modal price | Server-side GET, 10 s timeout, max 1 retry; records persisted with source + retrieval time + record hash; unique constraint prevents duplicates | Fetched on request; stored official records reused as persisted history | Explicit UNAVAILABLE state; records list empty; **no prices are ever estimated** | Observation (official records) | 2026-09-22 |
| 3 | Map tiles & location display | OpenStreetMap / Leaflet | `https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png` | ODbL — © OpenStreetMap contributors | Tiles only, plus farmer-selected farm/field coordinates | Leaflet client fetch (browser) | Browser tile cache | Tiles fail → blank tiles; markers unaffected | Reference (display only) | 2026-09-22 |
| 4 | Soil values | Farmer-entered / laboratory report / licensed geospatial dataset / district reference | Upload via `/api/fields/{id}/soil-tests` | Farmer-owned data; lab reports © respective laboratory; district reference clearly labelled | ph, EC, organic carbon, N, P, K + source_type + document | HTTPS form upload (PDF/JPG/PNG ≤ 5 MiB, magic-byte validated) stored under private `uploads/soil_reports/<user_id>/` | Persisted; never overwritten silently | Missing values remain unknown; district reference is always labelled as reference only | Farmer-entered / reference | 2026-09-22 |
| 5 | AI assistant explanations | Google Gemini (generativelanguage.googleapis.com) | `models/{model}:generateContent` | Google API terms; requires `GEMINI_API_KEY` | Explanatory text only — **never** weather, prices, soil values, farm history, stage, diagnosis or risk evidence | Server-side POST, 20 s timeout | None (not cached) | Explicit unavailable state in farmer mode; Student workspace uses the clearly-labelled AGRIQ rule-based knowledge engine instead | Generative explanation | 2026-09-22 |
| 6 | Crop-stage reference | AGRIQ internal (versioned `CROP_STAGE_REFERENCE_VERSION`) | `domain/catalogs/crop_stages.py` | AGRIQ curated reference | crop → stage day-windows | Local table | Static | Unavailable crops → farmer selects stage manually | Reference | 2026-09-22 |
| 7 | Crop / district / treatment knowledge | AGRIQ internal catalogues | `domain/catalogs/*.py` | AGRIQ curated agronomy content | crop profiles, district coordinates, pest/disease/soil libraries | Local | Static | n/a | Reference | 2026-09-22 |
| 8 | Farm Copilot knowledge grounding | ICAR / Govt. of Odisha / OUAT / KVK publications (allowlisted) | Manifest-registered official URLs; ingested via `python -m agriq.cli.ingest_knowledge` | Per-source `licence_note` recorded; organisations restricted to the approved allowlist | Sectioned advisory text (chunk + section reference + checksum) | Server-side download, 30 s timeout, 2 retries, 25 MB cap, SHA-256 checksum, duplicate skip | Persisted chunks; re-ingest skips unchanged checksums | Per-source failure reported; nothing partial marked ingested; **no unapproved source is retrievable** | Reference (review-gated) | 2026-09-22 |
| 9 | Copilot conversation & evidence records | AGRIQ internal (farmer's own data) | `conversations`, `messages`, `recommendations`, `assistant_runs` tables | Farmer-owned records; never shared cross-user | question, answer, evidence ids, confidence, provenance ids | Direct persistence on each turn | Retained per docs/FARM_COPILOT.md retention notes | n/a | Farmer-entered + system records | 2026-09-22 |

## Removed in Phase 1

- **Deterministic / seasonal weather model** — the prototype's offline
  weather generator has been removed from production execution
  (`tests/unit/test_weather_contract.py::test_deterministic_weather_removed_from_production_module`
  enforces this). Weather is live or explicitly unavailable; nothing else.
- **Fabricated district risk markers** — unanalysed districts display
  "Awaiting verified analysis." instead of offline-model scores.

## Data classes used in this register

- **Observation** — measured/recorded real-world values (provider or farmer).
- **Forecast** — provider predictions of future conditions (never labelled
  as on-field sensor readings).
- **Reference** — curated agronomic knowledge (catalogues, stage windows).
- **Farmer-entered** — the farmer's own records, including unknowns.
- **Generative explanation** — LLM output over verified context; never a
  source of facts.

## Phase 2 provenance commitments

- Every copilot answer carries an **evidence list** where each item names its
  source and timestamp (`observed_or_retrieved_at`) plus a freshness label
  (`live` / `cached` / `stale` / `unavailable` / `n/a`).
- Knowledge citations reference `knowledge_sources` rows only; the retriever
  cannot return unapproved or non-existent sources, so the LLM cannot invent
  a citation that is not in the registry.
- `assistant_runs` records which context record ids and which source ids were
  used for every model turn (prompt template version, model, status,
  timestamps) — a full audit trail without storing any secret or provider
  payload.
- Weather used by the copilot always comes from the field's registered
  coordinates and is labelled forecast vs observation; forecast is never
  presented as an on-field sensor reading.
- Market answers show only official AGMARKNET records; absence of records is
  shown as "Official matching records unavailable."

## UI provenance requirements (implemented)

Every live-data component shows source, last-updated time and state
(`LIVE SYNC` / `cached` / `UNAVAILABLE`). The dashboard's **Data Source and
Freshness** panel renders these chips server-side from the farmer context.

## Test fixtures policy

Synthetic values exist only under `apps/api/tests/`, are named as fixtures
(`FakeResponse`, `_png`, test passwords), never enter any production
database, never appear in the production UI, and are never presented as
model-training or evaluation data.
