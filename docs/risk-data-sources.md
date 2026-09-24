# Risk Data Sources (Phase 5)

Every input to the risk engine is real, provenance-carrying data. This file
records exactly what the engine consumes. Nothing here is synthesised.

## 1. Weather — Open-Meteo

| Aspect | Value |
| --- | --- |
| Provider | Open-Meteo (`https://api.open-meteo.com/v1/forecast`) |
| Endpoint | Existing Phase 1 integration (`integrations/weather/open_meteo.py`) |
| Data type | Current observation + hourly (12 h) + daily (7 d) forecast rows |
| Variables used | temperature_2m, relative_humidity_2m, rain, precipitation, wind_speed_10m, weather_code, daily max/min, daily precipitation_sum |
| Timestamp semantics | `provider_observed_at` (provider time) + `retrieved_at` (fetch time); forecasts are labelled forecast-model output, never sensor readings |
| Geographic coverage | Global; requested with the field's real stored coordinates |
| Authentication | None (public endpoint) |
| Rate limits / caching | TTLCache (30 min) + DB snapshot with `WEATHER_SNAPSHOT_TTL_SECONDS`; provider failure serves the last snapshot labelled `stale` or an honest unavailable |
| Freshness windows | fresh ≤ 1.5 h, aging ≤ 6 h, stale ≤ 36 h, expired beyond |
| Failure behaviour | `data_unavailable` assessment — no synthetic weather is ever produced |
| Type | Observation (current) + forecast (model output) |
| Last reviewed | 2026-09-23 |

## 2. Market — AGMARKNET via data.gov.in

| Aspect | Value |
| --- | --- |
| Provider | Government of India OGD platform, AGMARKNET resource `9ef84268-d588-465a-a308-a864a43d0070` |
| Endpoint | Existing Phase 1 integration (`integrations/market/agmarknet.py`) |
| Data type | Daily mandi arrivals: state, district, market, commodity, variety, arrival date, min/max/modal price |
| Variables used | modal_price, arrival_date (≥ 3 records ≤ 30 days old) |
| Timestamp semantics | `arrival_date` (provider) + `retrieved_at` (fetch time) |
| Geographic coverage | India (AGRIQ queries the farmer's district for Rice/Tomato) |
| Authentication | `DATA_GOV_IN_API_KEY` (server-side only, never exposed) |
| Rate limits | None imposed by the engine beyond the service's own caching |
| Failure behaviour | `data_unavailable` / `insufficient_data` — synthetic prices are strictly forbidden |
| Type | Observation (official records); descriptive screening only, never price advice or forecast |
| Last reviewed | 2026-09-23 |

## 3. Farmer-entered & persisted application data

| Source | Used for | Provenance |
| --- | --- | --- |
| Farmer profile | district scoping for market queries | farmer-entered at onboarding |
| Farm / field records | coordinates, irrigation type, soil type | farmer-entered; ownership-verified |
| Crop cycle | crop, variety, sowing/transplanting dates, stage | farmer-entered + existing crop-stage calculation (`farmer_confirmed_stage` takes precedence) |
| Field observations | latest field condition (e.g. waterlogged) | farmer-entered, timestamped |
| Crop-image analyses | supporting evidence (predicted class + confidence) | Phase 4 pipeline output; never treated as diagnosis |
| Weather snapshots | cached/stale weather with real timestamps | provider-persisted, `is_live` flag |

## 4. What the engine does NOT use

- No ML models, no embeddings, no synthetic datasets.
- No price forecasting, demand prediction or sell/hold signals (Phase 6 scope).
- No district-level agro-climatic tables that lack a verifiable source.
- No browser-supplied weather/market values.

All thresholds derived from these sources are documented in
`docs/risk-engine.md` and versioned as `agriq-risk-rules-v1` in
`domain/risk_engine/thresholds.py`.
