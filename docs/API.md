# AGRIQ AI — API Reference

Base URL (local): `http://127.0.0.1:5000`
All responses include security headers (CSP, nosniff, DENY, referrer policy).

## Pages (HTML)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/` | guest | Login page. Redirects to `/choose` when a session exists. |
| GET | `/login` | guest | Login page (Phase 7.1 — this route previously answered **405**, which is what broke sign-in on reload). `?mode=register` opens the account fields. |
| POST | `/login` | guest | Sign in (`user_contact`, `password`, `csrf_token`). Registration: send `auth_action=register` with `password_confirm` (the two passwords are compared server-side). Failures re-render with an `AUTH_*` code. |
| GET | `/forgot-password` | guest | Password-recovery request form. |
| POST | `/forgot-password` | guest | Request a reset link. Answers generically; returns `PASSWORD_RESET_EMAIL_UNAVAILABLE` when no email provider is configured (nothing is sent and no token is issued). |
| GET | `/reset-password?token=…` | guest | Set-new-password form for a single-use token. |
| POST | `/reset-password` | guest | Consume the token, store the new scrypt hash and revoke every session. |
| GET | `/choose` | user | Workspace chooser (Farmer / Student). |
| POST | `/choose-mode` | user | Select `mode=farmer\|student` + CSRF. Redirects to `/dashboard`. |
| GET/POST | `/dashboard` | user | Farmer: `crop, district, growth_stage, field_condition, leaf_photo` (multipart). Student: academic form fields. |
| POST | `/logout` | user | Revokes the server-side session row, then clears the cookie (CSRF required). GET fallback retained for the legacy link. |
| GET | `/farming-techniques` | user | **Farming Techniques** (Phase 7.2) — verified knowledge index. Query: `q`, `category`, `crop`, `region`, `evidence`, `mode=farmer\|student`, `page`, `lang`. Reachable from the side rail in **both** Farmer and Student Mode. |
| GET | `/farming-techniques/partials/results` | user | Same filters; returns only the results region (used by the page for a filter refresh without a full reload). |
| GET | `/farming-techniques/technique/<slug>` | user | Technique detail. Farmer order: what it is → why useful → suitable crops → when → how → what to avoid → safety → sources. Student order adds principle, background, applications, key terms and study summary from the **same** record. |
| GET | `/farming-techniques/pesticide/<slug>` | user | Regulatory pesticide record: label notice, manufacturing refusal, registered uses, PPE/PHI-when-stated, and `APPLICATION_DATA_UNVERIFIED` where the source is silent. Unknown or unverified slug → honest not-found panel. |

## Authentication & session management (Phase 7.1)

All endpoints below require an authenticated session; the identity is always the
server-side session row, never a value from the request. State-changing calls
need `X-CSRF-Token`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/auth/sessions` | The caller's own sessions (`current` flags the one in use). |
| POST | `/api/v1/auth/sessions/{id}/revoke` | Revoke one of the caller's sessions; revoking the current one signs the caller out. Another user's id is a 404. |
| POST | `/api/v1/auth/password` | Change password (`current_password`, `password`, `password_confirm`); revokes every session and asks the client to sign in again. |

Unauthenticated calls to protected JSON endpoints answer `401` with
`{"ok": false, "code": "AUTH_UNAUTHORIZED"}` (or `AUTH_ACCOUNT_DISABLED`,
`AUTH_SESSION_EXPIRED`) so clients can distinguish "signed out" from "missing
record". Cross-user access to an existing record remains `404`.

## JSON endpoints

### Farmer data API (Phase 1)

All endpoints require an authenticated session; ownership is re-verified on
every request (another farmer's record is indistinguishable from a missing
one — always 404). State-changing calls require the `X-CSRF-Token` header.

| Method | Path | Description |
|---|---|---|
| GET | `/api/profile` | Current farmer profile (or `null`). |
| POST | `/api/profile` | Create profile (full_name, preferred_language, state, district, village, consent_version). |
| PATCH | `/api/profile` | Update profile fields. |
| GET | `/api/farms` | List active farms. |
| POST | `/api/farms` | Register farm (name required; optional coordinates, area, ownership). |
| GET | `/api/farms/{id}` | Farm detail with fields. |
| PATCH | `/api/farms/{id}` | Update farm. |
| POST | `/api/farms/{id}/archive` | Archive farm (history preserved, never deleted). |
| GET | `/api/farms/{id}/fields` | List fields of a farm. |
| POST | `/api/farms/{id}/fields` | Add field (name required; area, soil_type, irrigation, coordinates). |
| GET | `/api/fields/{id}` | Field detail with crop cycles and soil tests. |
| PATCH | `/api/fields/{id}` | Update field. |
| POST | `/api/fields/{id}/archive` | Archive field. |
| GET | `/api/fields/{id}/soil-tests` | List soil records (every value source-labelled; unknowns stay null). |
| POST | `/api/fields/{id}/soil-tests` | Add soil record — JSON values or multipart with `report_document` (PDF/JPG/PNG ≤ 5 MiB). `source_type`: `laboratory_report`, `farmer_entered`, `geospatial_dataset`, `district_reference`. |
| GET | `/api/fields/{id}/crop-cycles` | List cycles (calculated + farmer-confirmed stage both returned). |
| POST | `/api/fields/{id}/crop-cycles` | Start cycle (crop_name, variety, season, dates). Stage auto-calculated from the versioned reference. |
| GET | `/api/crop-cycles/{id}` | Cycle detail. |
| PATCH | `/api/crop-cycles/{id}` | Update cycle (status, dates). Farmer confirmation never overwritten. |
| POST | `/api/crop-cycles/{id}/confirm-stage` | Farmer confirms/corrects stage (`{"stage": "..."}`). |
| POST | `/api/crop-cycles/{id}/archive` | Archive cycle. |
| GET | `/api/crop-cycles/{id}/observations` | Field timeline. |
| POST | `/api/crop-cycles/{id}/observations` | Record observation (multipart; optional image ≤ 5 MiB; type/validated). |
| GET | `/api/farmer-context` | **Shared Farmer Context** — one verified structure (farmer, farm, field, soil, cycle+stage, observations, weather provenance, market state). Accepts `farm_id`/`field_id`/`crop_cycle_id`. |
| GET | `/api/market-prices?commodity=` | Official AGMARKNET records for commodity (+ optional district). Always carries a machine-readable `state` (`OK`, `NO_OFFICIAL_RECORD`, `CONFIGURATION_ERROR`, `DATA_SOURCE_ERROR`) — never estimated prices. |
| GET | `/api/csrf-token` | Issue CSRF token for SPA fetches. |

Soil values are individually nullable: `"ph": null` means *unknown*, never
a generated estimate. Uploaded reports are stored privately under
`uploads/soil_reports/<user_id>/` and are not web-servable.

### Agricultural knowledge API (Phase 7.2 — Farming Techniques)

All routes require an authenticated session. Read routes are GET; only one POST
exists. There is **no ingestion or approval route** — importing and approving
knowledge is CLI-only, so no HTTP caller can insert or verify agricultural facts.

Every response is gated twice: the record must be `VERIFIED` **and** its
provenance row approved. Nothing unverified is ever serialised.

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/farming-techniques` | Verified listing. Query: `category` (`ancient`, `traditional`, `modern`, `organic_biological`, `modern_pesticide`), `crop`, `region`, `evidence`, `q`, `lang`, `mode`, `page`, `page_size` (clamped). Returns `status`, `count`, `pages`, `has_next`, `has_previous`, entries, facets and `awaiting_review`. |
| GET | `/api/v1/farming-techniques/search` | Text search over the documented text of verified records. `status` is `INSUFFICIENT_REAL_DATA` when nothing matches — never a fabricated result. |
| GET | `/api/v1/farming-techniques/categories` | The five categories with verified counts and i18n label keys; `DATA_UNAVAILABLE` while the base is empty. |
| GET | `/api/v1/farming-techniques/crops` | Crop facets (verified records only). |
| GET | `/api/v1/farming-techniques/regions` | Region facets. |
| GET | `/api/v1/farming-techniques/evidence-levels` | Evidence facets. |
| GET | `/api/v1/farming-techniques/sources` | Provenance index: title, organisation, URL, type, dates, licence note. |
| GET | `/api/v1/farming-techniques/status` | Coverage counters incl. `pending_records` awaiting agricultural review. |
| GET | `/api/v1/farming-techniques/<kind>/<slug>` | One verified record (`kind` = `technique`\|`pesticide`) with evidence rows, sources and freshness. Unknown slug → 404. |
| POST | `/api/v1/farming-techniques/ask` | Retrieval-grounded answer surface. Body `{"question": "…"}` (≤ 2000 chars). Returns reviewed passages with source attribution, or an honest state explained in words. |

Honest states returned by these routes:

```
DATA_UNAVAILABLE             nothing verified exists yet
INSUFFICIENT_REAL_DATA       the filters/search matched no verified record
PREPARATION_DATA_UNAVAILABLE no credible source documents a preparation
APPLICATION_DATA_UNVERIFIED  no current authority states how much / how often
KNOWLEDGE_MANUFACTURING_REFUSED  the question asks how to make a pesticide
```

`POST /api/v1/farming-techniques/ask` never calls a language model. It returns the
review-verified passages an AI is allowed to use plus the canonical safety state, so
a client cannot present generated agricultural text as verified knowledge. When
nothing verified matches, `answer` carries the localized explanation
(`message_key` + `hint_key`) rather than an empty string.

`lang` accepts `en` (default), `or` (Odia) and `hi` (Hindi); an unsupported value is
ignored and the next source (profile preference → cookie → `Accept-Language` →
English) decides. Interface strings are translated from the catalogs; agricultural
content is translated only from a reviewer-approved `knowledge_translations` row.
Where a preparation is described it is quoted from the cited source; AGRIQ never
computes, converts or transfers a quantity.

### Farm-to-Market API (Phase 6)

Additive to `GET /api/market-prices`. Session-authenticated; POST routes require
`X-CSRF-Token`; a foreign `field_id`/`crop_cycle_id` returns 404; all five
analysis routes share the analysis rate limit. Full reference:
`docs/market-api.md`.

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/market/overview` | Stored official prices, trend, volatility, demand state, per-variety market comparison. Optional `field_id`, `crop_cycle_id`, `commodity`, `quantity_quintals`, `transport_rate_per_km_quintal`, `transport_cost_total`. Blank cost fields stay unknown; an explicit `0` is a known cost. |
| GET | `/api/v1/market/forecast` | Chronological forecast over stored official history, or an explicit `insufficient_data` refusal. `horizon_days` 7 or 14. |
| GET | `/api/v1/market/demand` | Demand capability state — unavailable by design (`arrivals_not_published_by_configured_source`), never a proxy figure. |
| GET | `/api/v1/market/evidence` | Provenance, freshness policy and data-quality/quarantine report. No key material. |
| POST | `/api/v1/market/crop-options` | Crop-choice intelligence for the district (`crops` list ≤ 12, optional `season`, `include_market`). |
| POST | `/api/v1/market/sell-hold` | Evidence-based timing decision (`SELL_NOW`/`WAIT`/`MONITOR`/`INSUFFICIENT_DATA`) with `missing_information`. |
| POST | `/api/v1/market/logistics` | Market comparison with distance proxy, farmer-supplied costs (`quantity_quintals`, `transport_rate_per_km_quintal`, `transport_cost_total`, `input_cost_total`, `market_fee_total`) and `NET_VALUE_INCOMPLETE` economics. |

### Weather availability contract

`/api/live-weather` and the weather section of `/api/farmer-context`
return either provider data (`"available": true`, labelled `LIVE SYNC`, with
`provider_observed_at` + `retrieved_at`) or an explicit unavailable state:

```json
{"available": false, "live": false, "reason": "provider_request_failed",
 "message": "Verified data is currently unavailable."}
```

The prototype's offline seasonal model has been removed from production
execution and cannot appear in any response.

### `GET /healthz`
Liveness probe. No provider calls.
```json
{"status": "ok", "service": "agriq-ai", "time": "2026-09-22T15:46:12"}
```

### `GET /api/live-weather`
Query: `district`, `crop`, `growth_stage`, `field_condition` (allowlisted; invalid values fall back to defaults).
```json
{
  "weather_console": {
    "district": "Cuttack",
    "live_badge": "LIVE SYNC | OFFLINE FALLBACK",
    "updated_at": "03:20 PM",
    "source_note": "Live values are synced from Open-Meteo ...",
    "current": {"temp": 29.4, "humidity": 81, "rain": 0.5, "wind": 9.1,
                 "condition": "Overcast", "time": "22 Sep 2026 • 03:20 PM"},
    "daily": [ {"day": "23 Sep", "temp_min": 25.0, "temp_max": 32.0,
                 "rain": 1.2, "pop": 30, "wind": 10.0, "condition": "..."} ],
    "field_alert": "...", "disease_window": "...",
    "irrigation_note": "...", "spray_window": "..."
  },
  "risk_forecast": [ {"day": "23 Sep", "risk": 47, "status": "MODERATE",
                       "color": "yellow", "temp": 28.5, "humidity": 78, "rain": 6.0} ]
}
```
Provenance contract (Phase 7.3). `live_badge` is `LIVE SYNC` only when
Open-Meteo answered, `STALE` when a stored snapshot had to stand in, otherwise
`UNAVAILABLE` — there is no seasonal/offline fallback model in production.
The console also carries `state`, `state_message`, `location_source`
(`field_coordinates` | `farm_coordinates` | `district_centre`) and a freshness
block (`freshness_status`, `age_seconds`, `ttl_seconds`, `is_stale`).

Unavailable example (no location stored):
```json
{
  "weather_console": {
    "district": "", "available": false, "live_badge": "UNAVAILABLE",
    "state": "INVALID_LOCATION",
    "state_message": "Location is required to retrieve weather data. Add your district or field coordinates to receive verified weather.",
    "reason": "no_location", "current": {"temp": null},
    "daily": [], "source_note": "Weather comes live from Open-Meteo for a real location..."
  },
  "risk_forecast": []
}
```
Every state is one of: `OK`, `DATA_UNAVAILABLE`, `DATA_SOURCE_ERROR`,
`INVALID_LOCATION`, `DATA_STALE`, `CONFIGURATION_ERROR`, `NO_OFFICIAL_RECORD`.
A payload never carries a value that was not retrieved, and a failure is never
reported as data.

### `POST /ask-ai`
Headers: `Content-Type: application/json`, `X-CSRF-Token` (required for
authenticated sessions). Body: `{"question": str(≤2000), "context": {str:str}}`.

**Farmer mode (Phase 1):** the request loads the shared farmer context
from the authenticated user, passes ONLY verified structured context to
Gemini, persists the conversation with per-message provenance, and stores
an evidence-backed recommendation. Responses:

```json
{"answer": "...", "ok": true, "source": "gemini",
 "source_label": "Google Gemini with verified AGRIQ context",
 "sources": {"verified_provider_data": {...}, "unknown_or_unavailable": [...]},
 "recommendation": {"id": 12, "requires_expert_confirmation": true}}
```

Without Gemini configured (or on failure) the answer is an explicit
unavailable state — no scripted answer is labelled as AI:

```json
{"answer": "The AI assistant is not available right now...",
 "ok": false, "source": "unavailable", "reason": "gemini_not_configured"}
```

**Student/Research mode:** unchanged knowledge-engine behaviour, clearly
labelled (`source: "knowledge_engine"`,
`source_label: "AGRIQ knowledge engine (rule-based reference)"`).

Errors: empty question → guidance message; invalid CSRF → 403; rate limit
→ 429; internal failure → safe fallback message (no stack traces).

## Error format (JSON routes)

```json
{"ok": false, "error": "Live weather is temporarily unavailable."}
```
`400` validation/CSRF · `401` unauthenticated API · `403` CSRF mismatch ·
`404` not found · `413` upload too large · `429` rate limited ·
`500` internal (generic message only).

## Rate limits (per IP)

| Route | Limit |
|---|---|
| POST `/login`, POST `/choose-mode` | 8/minute |
| POST `/ask-ai` | 12/minute |
| POST `/dashboard` | 20/minute |
| `/api/v1/market/*` (Phase 6 analysis routes) | `AGRIQ_RATE_ANALYSIS` (default 20/minute) |
| GET `/api/live-weather` | 30/minute |

## Upload rules

- Images (observation/LeafScan): `.jpg .jpeg .png .webp` · Max **5 MiB**
- Soil reports: `.pdf .jpg .jpeg .png` · Max **5 MiB**
- Both validated by extension AND magic bytes; filenames are randomised
  server-side and files are stored under the private `uploads/` folder —
  never inside the web-servable static directory.
- Decoded safely with Pillow; corrupt/mismatched files are rejected
  (`413`/safe state), never processed partially.
- LeafScan output is **screening** support, not diagnosis.
- Global request ceiling: 8 MiB (`MAX_CONTENT_LENGTH`).
