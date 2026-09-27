# Phase 7.3 — Real Weather + Real Mandi Data: audit, root causes and verification

**Scope:** make the two existing external integrations (Open-Meteo weather, and
AGMARKNET prices via data.gov.in) reliably retrieve, validate, normalize and
**display** real data — and never replace a failure with a value.

**Baseline at the start of this phase:** Phase 7.2 — 546 passed + 1 skipped,
migration head `0008_farming_knowledge`, 92 routes.

**Result after this phase:** 609 passed + 1 skipped, migration head unchanged
(no schema change was required), 92 routes (no new endpoint was required),
`flake8` clean, `compileall` clean, `node --check` clean on all 9 JS modules,
`validate_project.py` PASSED, `check_environment.py` all pass,
`check_auth_flow.py` 14/14.

---

## 1. The two reported symptoms, traced to their causes

The user reported exactly two visible strings:

| Reported | Where it renders |
| --- | --- |
| `Verified data is currently unavailable.` | `templates/dashboard/_farm_data.html` — "Data Source and Freshness" panel, weather chip |
| `Official records shown when returned by data.gov.in.` | same panel, mandi chip |

Both sentences live in the same five-line block. Neither was a consequence of
the providers being down. **Four** distinct defects were found, three of them
plain bugs.

### Root cause A — the weather chip could never report a healthy provider

`api/dashboard.py` built the context with `include_weather=False`:

```python
context = farmer_context_service.build_farmer_context(user.id, include_weather=False)
```

`build_farmer_context` then forced:

```python
context["weather"] = {"available": False, "reason": "no_field_selected",
                      "message": "Register a field with coordinates to receive weather."}
```

and the template renders `'Verified data is currently unavailable.'` whenever
`weather.available` is falsy. So the chip said "unavailable" on **every** page
load regardless of provider health — while `GET /api/live-weather` worked
perfectly.

Measured, live, from this machine at the time of the audit:

```
get_weather("Cuttack") -> available=True temp=32.2 condition="Clear sky"
                          hourly=12 rows daily=7 rows
curl -o /dev/null -w '%{http_code}' api.open-meteo.com/v1/forecast?...  -> 200
```

A second, independent gap: even with `include_weather=True`, weather was only
requested when a *field* existed, and `weather_service._resolve_coordinates`
returned nothing when neither the field nor its farm carried coordinates — even
though the farmer's **district** is stored and the district catalogue holds real
administrative-centre coordinates. A farmer with a district and no GPS got no
weather at all.

### Root cause B — every mandi price was silently discarded

`integrations/market/agmarknet.py`:

```python
def _price(key: str) -> float | None:
    value = record.get(key)          # `key` is actually the already-read VALUE
    ...

"modal_price": _price(record.get("modal_price") if "modal_price" in record
                      else record.get("modal_price_rs")),
```

`_price` received a **value** (`"2400.00"`) and looked it up as a **key**
(`record.get("2400.00")` → `None`). Every `min_price`, `max_price` and
`modal_price` therefore normalized to `None`, so even a perfectly healthy
provider response would have displayed no prices at all. This is the single most
damaging defect found in the phase, and it was invisible without a real provider
response — which is why the new tests pin prices explicitly (including the
`_rs`-suffixed provider spellings).

### Root cause C — the mandi chip was a promise, not a state

* `farmer_context.build_farmer_context` hardcoded
  `context["market"] = {"available": False, "reason": "not_requested"}` — a
  placeholder that could never reflect stored official records, so the chip
  could not show real rows even when `market_price_records` held them.
* The template hardcoded `class="data-source-chip unavailable"` and the fixed
  sentence, so the chip was permanently styled as unavailable.

### Root cause D — an unknown district silently became Cuttack

`domain/catalogs/districts.coordinates_for()` returns
`DISTRICTS.get(name, DISTRICTS["Cuttack"])`. `coordinates_for_exact` did not
exist, and `rate`/weather lookups used the defaulting version, so
`get_weather("Atlantis")` returned **Cuttack's** weather as if it were the
caller's location. Weather (or prices) answered for the wrong place is worse
than an explicit failure.

### Root cause E — one caller's provenance leaked to another

`open_meteo.get_weather` cached the **whole stamped payload** keyed only on
coordinates. Two callers resolving the same coordinates from different places
(exact field coordinates vs the district centre) shared one entry, so the second
caller inherited the first caller's `location_source` — i.e. AGRIQ could claim
field-level precision for a district-centre value. Found by the new tests
(surfaced as order-dependent failures), fixed by caching the provider payload
and stamping caller-specific fields on a copy.

---

## 2. Why live mandi prices are `CONFIGURATION_BLOCKED` here, with evidence

`DATA_GOV_IN_API_KEY` is unset in `.env` **and** absent from the OS environment
(checked: `User=False`, `Machine=False`). Per the request, keyless official
alternatives were researched before accepting that state.

| Candidate official source | Result | Evidence (real requests, 2026-09-27) |
| --- | --- | --- |
| data.gov.in OGD resource `9ef84268-…` (the integration's configured source) | **Key required**; keyed calls currently 502/time out | keyless → `400 {"error": "Authorization field missing"}` (fast, repeatable); with a key (including data.gov.in's own published *sample* key) → `502 Bad Gateway` / `curl (28)` timeout across 4 attempts |
| `api.agmarknet.gov.in/v1` — the Government's own Agmarknet 2.0 API (found in the official SPA bundle as `REACT_APP_API_URL`) | **Reference data is open; every price report is provider-gated** | `GET /daily-price-arrival/filters` → `200` (37 states, 751 districts, 4171 markets, 605 commodities, 2154 varieties, date range 2025-11-07 → 2026-09-27); `POST /daily-price-arrival/report` → `400 {"code":"TOKEN_OR_CAPTCHA_REQUIRED"}`; `POST …/daily-report-weighted` → same; `/msp-cmdt`, `/market`, `/list-market` → `403 Authorization header missing` |
| `osamb.odisha.gov.in/Grievance/public/price_trend` — Odisha State Agricultural Marketing Board (state's own daily price dissemination) | **Not machine-readable without a stakeholder login** | `GET` renders an empty table (1 `<tr>`, headers only) with no filter fields; `POST` with the page's *own* CSRF tokens returns the identical empty table |
| `robots.txt` on `agmarknet.gov.in` | Explicitly permissive | `User-agent: *` / `Allow: /` (only `/signin`, `/forgotpassword`, `/otpconfirm`, `/resetpassword` disallowed) — so the permissiveness is not the blocker; the captcha is |

**Conclusion (documented, not assumed):** there is **no keyless official mandi
price source**. The provider's own bot protection on the price report is
respected — AGRIQ does **not** attempt to defeat a captcha, and does not scrape a
page that requires a stakeholder login. Live prices therefore require the
deployment's own free data.gov.in key; without it the honest state is
`CONFIGURATION_ERROR`, which names the variable and shows persisted official
records instead.

`.env.example` records this reasoning next to `DATA_GOV_IN_API_KEY`, and
`scripts/check_live_data.py` reproduces the evidence on demand.

---

## 3. What was changed

### 3.1 One machine-readable state vocabulary — `core/constants.py`

`OK`, `DATA_UNAVAILABLE`, `DATA_SOURCE_ERROR`, `INVALID_LOCATION`, `DATA_STALE`,
`CONFIGURATION_ERROR`, `NO_OFFICIAL_RECORD`, `PROVIDER_ACCESS_GATED`, plus
stable failure reason codes and per-state messages. Every payload now carries
`state` **and** `state_message` while keeping the canonical `message` sentence
that existing consumers assert on. A successful payload has the same shape as a
failed one (`state="OK"`), so no consumer has to infer health from a missing key.

Record-age windows were deliberately **not** redefined: `domain/risk_engine/
freshness.classify` remains the single owner (weather fresh ≤1.5 h/aging ≤6 h/
stale ≤36 h; market ≤24/≤72/≤240 h).

### 3.2 Weather — `integrations/weather/open_meteo.py`, `services/weather_service.py`

* `fetch_weather()` always returns a payload with a state; timeouts, 5xx, 4xx,
  malformed JSON, bodies with no weather section and network errors are each
  classified (`provider_timeout`, `provider_http_error`,
  `provider_malformed_response`, `provider_request_failed`).
  `fetch_live_weather()` keeps its old `dict | None` contract as a wrapper.
* Coordinate validation: `None`, non-numeric, out of range, and exact `0,0`
  (the classic unset-form placeholder) → `INVALID_LOCATION`. A *sparse* provider
  response is still returned as retrieved — missing fields stay `None` rather
  than being reclassified as malformed.
* `get_weather(district=…)` resolves the district through the new
  `coordinates_for_exact` (case-insensitive, **never** substitutes another
  district) and records `location_source`, `latitude`, `longitude`.
* `get_district_weather()` gives a farmer without GPS real weather for the
  district administrative centre, labelled as coarser than field coordinates
  (satisfies "use the existing profile location; do not ask repeatedly").
* `get_field_weather()` now resolves field → farm → district centre, persists a
  snapshot only for exact coordinates, serves a stored snapshot as an explicit
  `DATA_STALE` when the provider fails, and attaches the canonical freshness
  block (status, age seconds, TTL, `is_stale`).
* `_has_no_payload_sections()` distinguishes a real-but-sparse body from a
  malformed one.

### 3.3 Mandi — `integrations/market/agmarknet.py`, `services/market_service.py`

* **Price coercion fixed** (root cause B) plus `_rs`/`minimum_price` provider
  spellings, thousands separators, and `NA`/`N/A`/`-`/`0` → `None` (*a zero
  price is not a price*).
* Bounded pagination: up to `MAX_PAGES` (3) × `PARAM_LIMIT` (10) rows via
  `offset`, stopping on a short page. A later page failing keeps the real rows
  already retrieved instead of discarding a partial success.
* Failure classification, including the OGD platform's keyless 400
  (`{"error": "Authorization field missing"}`) and 401/403 → `CONFIGURATION_ERROR`
  with `api_key_not_configured`; timeouts/5xx → `DATA_SOURCE_ERROR`.
* `retrieved_at`/`fetched_at` are now **AGRIQ's** fetch time (previously the
  provider's `updated_date` was mislabelled as our retrieval time);
  `provider_updated_at` and `reported_total` carry the provider's own metadata.
* Provider answered with zero rows → `available: True`, `state:
  NO_OFFICIAL_RECORD` and "No official mandi record was returned for this crop,
  district and date." — a real answer, never dressed up as an outage.
* Normalization keeps provider values verbatim; every persisted record now
  carries `record_status` from the canonical classifier, so an old arrival date
  reads `stale`/`expired` rather than as today's price.
* `context_state()` replaces the context placeholder: credential presence,
  persisted official record count, newest arrival date and its freshness, with
  `fetched_live: False` (a dashboard load never fans out to the provider).
  `persisted_summary()` is a read-only count/max query with no network call.

### 3.4 Context, API and UI

* `farmer_context`: weather is really requested; no profile → explicit
  `INVALID_LOCATION` ("add your district…") instead of an outage-sounding
  message; market is a real state.
* `api/dashboard.py`: `include_weather=True`.
* `templates/dashboard/_farm_data.html`: both chips render the real state —
  provider + `district centre` basis + retrieval time + `marked stale`, or the
  cause-specific sentence; the mandi chip is no longer hardcoded `unavailable`.
* `templates/dashboard/index.html`: an unavailable/sourceless weather console
  renders one state tile with the real cause instead of `None°C` / `None mm`, and
  an empty outlook states why; `weather.js` prefers `state_message` so the
  server-rendered and refreshed views agree; `weather_advisory` passes the state
  through and no longer blames the network for every outcome.

### 3.5 Configuration

No new environment variable was needed: Open-Meteo requires no credential, and
`DATA_GOV_IN_API_KEY` already existed. Its `.env.example` comment now states that
it is *required for live prices*, what the provider answers without it, and why
no keyless alternative exists. No key value is committed anywhere.

---

## 4. Real-data verification (not unit tests)

`python scripts/check_live_data.py` — run from the repository root against the
real providers on 2026-09-27:

```
Configured DATA_GOV_IN_API_KEY: no

=== Weather: Open-Meteo (live) ===
[PASS] weather: Cuttack 31.9°C, humidity 61.0%, wind 8.3 km/h, 'Clear sky'
        provider=Open-Meteo observed_at=2026-09-27T15:45
        retrieved_at=2026-09-27T10:28:34+00:00 freshness=fresh age_s=0
        coords=20.4625,85.883 location_source=verification
        hourly rows=12 daily rows=7

=== Weather: invalid location handling ===
[PASS] weather_invalid_location: state=INVALID_LOCATION reason=invalid_coordinates

=== Mandi: AGMARKNET via data.gov.in (live) ===
[INFO] mandi: CONFIGURATION_BLOCKED - DATA_GOV_IN_API_KEY is not configured
        provider refusal: HTTP 400 {"error": "Authorization field missing"}

=== Provider audit: official keyless surfaces ===
[PASS] agmarknet_reference_filters: HTTP 200 - reference data only, no prices
[PASS] agmarknet_states: HTTP 200 - reference data only, no prices
[INFO] agmarknet_price_report: HTTP 400 {"detail":"Captcha key and captcha value
        are required.","code":"TOKEN_OR_CAPTCHA_REQUIRED"}
```

Honest reading of that output:

* **Weather: verified live.** Real provider values, real retrieval timestamp,
  real coordinates, freshness `fresh`.
* **Mandi: `CONFIGURATION_BLOCKED`.** The parse/normalize/serialize path is
  verified against real provider *shapes* in the test suite (including the
  `_rs` field spellings and the keyless-400 body the platform really returns),
  but a **live** official record could not be retrieved from this deployment,
  because no key is configured and the OGD endpoint currently refuses keyed
  calls with 502/timeout anyway. This is stated, not hidden.
* The script is **not** wired into CI: it depends on live network access, and a
  flaky external dependency must not gate the build. It is documented as a
  manual verification, alongside the fixed-CI steps.

### 4.1 Live browser verification of the two reported panels

Driven through the running application on `http://127.0.0.1:5000` (an isolated
preview database, after registering a real account and saving a farmer profile
with district Cuttack). The "Data Source and Freshness" panel then rendered:

```
Weather: Open-Meteo (district centre) • updated 2026-09-27T10:51:49.695813+00:00
Mandi prices: Live mandi prices need a data.gov.in API key on this deployment
              (DATA_GOV_IN_API_KEY). Until it is configured AGRIQ shows persisted
              official records only, and never an estimated price.
Soil: farmer-entered or lab report — never estimated.
Map: district risk shown only after analysis; unanalysed districts await verified analysis.
```

Before the same profile existed, the weather chip read
"Location is required to retrieve weather data. Add your district or field
coordinates to receive verified weather." — the invalid-location state, not an
outage. `GET /api/live-weather` in that session returned `state=OK`,
`live_badge=LIVE SYNC`, `temp=31.5`, `humidity=66`, `rain=0`, `wind=7.1`,
`condition="Clear sky"`, `provider_observed_at=2026-09-27T16:15`, 7 daily rows and
7 risk-forecast rows, with **no console errors**.

So the sentence the user reported is gone: a healthy provider is now reported as
healthy in the UI, and a failure names its own cause.

---

## 5. Tests added (63 new; nothing weakened)

`tests/unit/test_provider_states.py` (37) — weather classification for timeout /
5xx (retried `MAX_RETRIES+1`) / 4xx (not retried) / malformed JSON / sectionless
payloads; sparse payloads returned as retrieved; invalid and unset coordinates;
unknown district never resolving to another; provenance and coordinates on
success; freshness for untimestamped, old and just-retrieved payloads; mandi
missing-key (no request attempted at all), blank commodity, 403 and the
`Authorization field missing` 400, 5xx, timeouts; price parsing incl. `_rs` and
zero-is-not-a-price; bounded pagination and page offsets; `MAX_PAGES` stop;
later-page failure retention; zero-records state; wrong-typed `records`;
`retrieved_at` = AGRIQ fetch time; and two credential-leak tests asserting the
key never appears in any payload.

`tests/integration/test_live_data_provenance.py` (20) — configuration error
without a price; provider failure as `DATA_SOURCE_ERROR`; the configured key
never reaching a response; persisted official records reported with their dates;
old records as `DATA_STALE`; `record_status` across the canonical windows
(and `unavailable` without a date); district-centre weather fallback with its
basis and freshness; `INVALID_LOCATION` without a location; weather failure
state; farmer-context weather/market states; and the four **direct regressions**
for the reported symptoms — a healthy provider is reported as available, a
failure names its cause, the mandi chip states the missing credential, and
stored official records are displayed with their arrival dates.

`tests/integration/test_copilot.py::test_copilot_unavailable_weather_is_not_simulated`
was updated (not weakened): it now patches the classified entry point and
therefore also proves the failure *state* reaches the copilot.

---

## 6. Security

* The credential is read server-side only (`current_app.config`), never logged,
  never echoed; response payloads are asserted key-free in two tests.
* Outbound requests are fixed-URL (no user-supplied host), so there is no SSRF
  surface introduced; `data.gov.in` URLs are configuration, not request input.
* Timeouts (8 s weather, 10 s mandi), bounded retries (one) and bounded
  pagination (3 pages) cap external work; failures are cached so an outage
  cannot become a request storm.
* Error bodies from the provider are truncated to 400 characters before
  classification and are never returned to a client.
* Bandit (CI gate: no HIGH/MEDIUM) re-run clean; `node --check` clean on all JS.
* No new dependency; no `eval`/`innerHTML` sink added (the `weather.js` change
  only selects a different message string).

---

## 7. Honest limitations (unchanged by this phase)

1. **Live mandi prices are `CONFIGURATION_BLOCKED`** on this deployment: no
   `DATA_GOV_IN_API_KEY`, and the OGD endpoint is currently also failing keyed
   calls with 502/timeouts. Persisted official records and explicit
   configuration states are what AGRIQ can honestly show.
2. **No keyless official mandi source exists** (evidence in §2). AGRIQ does not
   defeat the provider captcha and does not scrape a login-gated page.
3. Weather is verified for real locations; a district-centre value is coarser
   than field coordinates and is labelled as such rather than presented as
   field-level precision.
4. Retrieval remains **lexical/on-demand**: no background polling loop was added
   (deliberately), so freshness is bounded by the configured snapshot TTLs
   (`WEATHER_SNAPSHOT_TTL_SECONDS` 1800 s, `MARKET_SNAPSHOT_TTL_SECONDS` 21600 s)
   and by how often a farmer opens the pages.
5. The development database at `apps/api/instance/agriq.db` was not touched, and
   no migration was added.
