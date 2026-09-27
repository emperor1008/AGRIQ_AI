# Market Data Sources (Phase 6)

Every input to the Farm-to-Market Optimizer is a real, provenance-carrying
value. This file records exactly what the engine consumes. Nothing here is
synthesised, backfilled or interpolated.

## 1. Market prices — AGMARKNET via data.gov.in

| Aspect | Value |
| --- | --- |
| Provider | Government of India OGD platform, AGMARKNET daily mandi prices |
| Resource | `9ef84268-d588-465a-a308-a864a43d0070` (overridable via `DATA_GOV_IN_MARKET_RESOURCE_ID`) |
| Endpoint | Existing Phase 1 integration (`integrations/market/agmarknet.py`), called through `services/market_service.py` |
| Fields used | state, district, market, commodity, variety, `arrival_date`, min/max/modal price |
| Canonical unit | `INR_per_quintal` — the unit the provider publishes. No conversion is invented; a record whose unit cannot be established is quarantined |
| Timestamp semantics | `arrival_date` (the market's own observation date) + `retrieved_at` (AGRIQ's fetch time) |
| Geographic coverage | India; AGRIQ requests the farmer's district (falling back to state-wide) |
| Authentication | `DATA_GOV_IN_API_KEY`, server-side only, and **required for live prices**. The key, its value and its environment-variable name never appear in any response |
| Caching | Per-app TTL cache keyed by (commodity, district, state); window = `MARKET_SNAPSHOT_TTL_SECONDS` (default 21600 s). Failures are cached too, so an outage cannot turn into a request storm |
| Pagination | Bounded: at most `MAX_PAGES` (3) provider pages per call via `offset`, stopping on a short page. A later page failing keeps the real rows already retrieved |
| Price parsing | Provider price text → float. `NA`/`N/A`/`-`/`0` stay `None` (a zero price is not a price) and the provider's `_rs`/`minimum_price` spellings are accepted. **Phase 7.3 fixed a defect here**: the previous implementation looked a price *value* up as a *key*, so every `min`/`max`/`modal` price silently became `None` even on a healthy response |
| Freshness | Each record's `record_status` comes from the canonical classifier — `domain.risk_engine.freshness.classify` (market: fresh ≤24 h, aging ≤72 h, stale ≤240 h, expired beyond). An old arrival date is reported as stale/historical, never as today's price |
| Failure behaviour | Machine-readable `state` (see §7) with a cause-specific `state_message`: `CONFIGURATION_ERROR` (no/invalid key — the variable is named, never its value), `DATA_SOURCE_ERROR` (timeout/5xx/malformed), `NO_OFFICIAL_RECORD` (the provider answered with zero rows — a real answer, not an outage). **No price is ever estimated** |
| Provenance | `retrieved_at`/`fetched_at` are AGRIQ's own fetch time; `provider_updated_at` and `reported_total` carry the provider's metadata (previously the provider's `updated_date` was mislabelled as our retrieval time) |
| Type | Observation (official records), fetched on request |

## 2. Stored official price history — AGRIQ persisted rows

| Aspect | Value |
| --- | --- |
| Provider | AGRIQ itself: rows returned by the source above and persisted unmodified in `market_price_records` |
| Fields | as returned by AGMARKNET, plus `source`, `retrieved_at` and a `raw_record_hash` unique constraint that prevents duplicates |
| History depth | exactly as long as this deployment has been collecting. **It is never backfilled, interpolated or gap-filled**, so a thin history stays thin and the features that need more say so |
| Used for | trend, volatility, `latest_by_market`, chronological forecast, crop-choice price context, market comparison, and the dashboard's "Data Source and Freshness" chip |
| Context reads | `market_service.context_state()` reports the credential state, the persisted record count and the newest arrival date **without any provider call**, so a dashboard load cannot fan out to the network. It marks `fetched_live: False` |
| Type | Observation (official records) |

## 3. Phase 5 risk assessments (read-only)

Stored, persisted risk runs for the field (`domain/risk_evaluation` provenance
included). Phase 6 never recomputes risk and never invents one: with no stored
run the payload says `risk_context: []`.

## 4. Weather — Open-Meteo (via the existing weather service)

Current conditions for the field's real stored coordinates, used only by
agronomic suitability. Weather availability is explicit; an unavailable weather
provider leaves the weather-dependent suitability factors `unknown` rather than
assumed favourable. No synthetic weather is produced.

## 5. Farmer-entered & curated data

| Source | Used for | Provenance |
| --- | --- | --- |
| Farmer profile | district/state scoping of every price query | farmer-entered at onboarding |
| Farm / field | coordinates (distance proxy), area, irrigation type | farmer-entered; ownership-verified |
| Crop cycle | crop, variety, season, stage | farmer-entered + the existing crop-stage calculation |
| Soil test values | suitability context where the farmer recorded them | farmer-entered; unknown stays unknown |
| `domain/catalogs/crops.py` | temperature/humidity/rainfall windows, season, soil, storage class, perishability | AGRIQ curated reference (`agriq-crop-catalog`) |
| `domain/catalogs/districts.py` | district coordinates, agro-climatic profile, documented main crops | AGRIQ curated reference |

## 6. What the optimizer does NOT use

- **No demand or arrival quantities.** The configured resource publishes prices,
  not arrivals, so demand reports
  `arrivals_not_published_by_configured_source` and no proxy percentage is shown.
- **No transport tariffs.** AGMARKNET has no freight rates and AGRIQ holds no
  licensed rate card, so freight enters only as the farmer's own figure — either a
  ₹/quintal/km rate applied to the distance proxy or the total they pay for the
  trip. With neither supplied the result is `NET_VALUE_INCOMPLETE` naming what is
  missing; no tariff is ever inferred from a price or a distance.
- **No yields, input costs or market coordinates.** Market names carry no
  coordinates, so distance is a documented straight-line proxy to the market's
  district centre, and no yield or input-cost figure is ever estimated.
- **No browser-supplied prices.** Prices, quantities and rates arrive only
  through the typed service arguments; nothing from the request body is treated
  as an observation.
- **No backtested accuracy claim.** Confidence is `not_calibrated` everywhere.

## 7. Provider states (Phase 7.3)

Every price payload — success or failure — carries a machine-readable `state` and
a cause-specific `state_message`, so no consumer has to infer health from prose:

| State | Meaning | What the farmer sees |
| --- | --- | --- |
| `OK` | Official records were retrieved (or are stored) and are recent | The records with their arrival dates |
| `NO_OFFICIAL_RECORD` | The provider answered, with zero rows for this crop/district/date | "No official mandi record was returned for this crop, district and date." |
| `DATA_STALE` | Records exist but the newest arrival date is beyond the market freshness windows | The records, explicitly labelled historical/stale |
| `CONFIGURATION_ERROR` | No key configured, or the provider refused the key (its keyless answer is `400 {"error": "Authorization field missing"}`) | The variable name and what still works — never a price |
| `DATA_SOURCE_ERROR` | Timeout, 5xx, or a malformed body | "The Government mandi service is temporarily unavailable…" |

### Why live prices need a credential (researched, not assumed)

There is **no keyless official mandi price source**, verified by direct request on
2026-09-27:

* the configured data.gov.in resource rejects a keyless call with
  `400 Authorization field missing`;
* the Government's own Agmarknet 2.0 API (`api.agmarknet.gov.in/v1`) serves
  reference data openly (`/daily-price-arrival/filters`, `/location/state` → 200)
  but gates every price report: `POST /daily-price-arrival/report` →
  `400 TOKEN_OR_CAPTCHA_REQUIRED`, and `/msp-cmdt`, `/market`, `/list-market` →
  `403 Authorization header missing`;
* the Odisha State Agricultural Marketing Board's public price-dissemination page
  renders no rows without a stakeholder login.

AGRIQ therefore does **not** defeat the provider's captcha and does not scrape a
login-gated page. It reports `CONFIGURATION_ERROR`, names the variable, and keeps
showing persisted official records. Reproduce with
`python scripts/check_live_data.py`.
