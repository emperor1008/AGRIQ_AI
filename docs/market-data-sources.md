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
| Authentication | `DATA_GOV_IN_API_KEY`, server-side only. The key, its value and its environment-variable name never appear in any response |
| Caching | Per-app TTL cache keyed by (commodity, district, state); window = `MARKET_SNAPSHOT_TTL_SECONDS` (default 21600 s). Failures are cached too, so an outage cannot turn into a request storm |
| Failure behaviour | Explicit states only: `api_key_not_configured`, `provider_request_failed`. Never an estimated price |
| Type | Observation (official records), fetched on request |

## 2. Stored official price history — AGRIQ persisted rows

| Aspect | Value |
| --- | --- |
| Provider | AGRIQ itself: rows returned by the source above and persisted unmodified in `market_price_records` |
| Fields | as returned by AGMARKNET, plus `source`, `retrieved_at` and a `raw_record_hash` unique constraint that prevents duplicates |
| History depth | exactly as long as this deployment has been collecting. **It is never backfilled, interpolated or gap-filled**, so a thin history stays thin and the features that need more say so |
| Used for | trend, volatility, `latest_by_market`, chronological forecast, crop-choice price context, market comparison |
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
