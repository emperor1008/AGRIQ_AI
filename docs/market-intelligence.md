# Market Intelligence — Product Overview (Phase 6)

The **Farm to Market** panel answers the farmer's four market questions — *what
should I grow, where should I sell, when should I sell, and what is it worth* —
from the same verified data that powers the rest of AGRIQ AI, and says "I cannot
tell you" whenever the evidence does not exist.

## What the farmer sees

The panel sits in the existing dashboard alongside the Crop Risk panel and uses
the existing design system (cards, status badges, provenance chips). It has four
actions: **Refresh prices**, **Sell or wait?**, **Crop options** and **Compare
markets & costs**. When the farmer has an active crop cycle the official-price
card loads automatically.

The **Sale details for a cost check** block holds the farmer's own figures —
quantity to sell, transport rate or total freight, input cost, market fee, and a
three-state storage answer (*Not stated* / yes / no). It ships empty and is never
pre-filled: a blank field stays unknown, and only what the farmer types can
complete a net value.

1. **Official prices** — the newest stored AGMARKNET record per market for the
   farmer's crop and district, with variety, price date and source. Above it, a
   trend badge (direction + % change) or the explicit "trend unavailable".
2. **Market comparison** — markets grouped by commodity and variety, each with
   its modal price, the straight-line distance proxy when one is computable, and
   the economics row: gross value, or "Net value incomplete — missing: …".
3. **Sell or wait** — a decision word (Sell now / Wait / Monitor / Not enough
   evidence), the evidence points that produced it, the information still
   missing, any Phase 5 risk in context, and "Confidence not calibrated — no
   probability is claimed."
4. **Crop options** — candidate crops for the district ranked by agronomic
   suitability, then by verified price context, each with its first reason and
   `no stored price` where AGRIQ holds no official record for that crop.
5. **Value and cost check** — after **Compare markets & costs**, the comparison
   with a gross value per market and either an estimated net value (only when
   every cost came from the farmer) or "Net value incomplete — missing: …". The
   gross value is price × quantity and is never called profit.

## What the numbers mean

- **Prices** are official AGMARKNET *provisional daily* modal prices (₹/quintal).
  They are never called live, and a `PROVISIONAL`/freshness chip states their age.
- **Trend, volatility and comparison** are arithmetic over stored official
  records only. Varieties and commodities are never blended, and paddy and rice
  are treated as separate provider series rather than mixed into one.
- **A forecast is only shown** when enough official history exists, and it is
  published with its training/validation/evaluation periods, the selected model,
  the candidate metrics and whether it beat the naive baseline. The prediction
  interval is labelled as a dispersion approximation, not a calibrated interval.
- **A net value is only shown** when the farmer supplies quantity and every cost
  component. Otherwise the row says `NET_VALUE_INCOMPLETE` and names what is
  missing — a gross value is never relabelled as profit.
- **Timing advice requires evidence.** A storable crop and a single price are not
  enough; the panel says "not enough evidence" and lists what is missing.
- **Every evidence point states which way it points** ("favours selling", "favours
  waiting"), and facts that moved the decision are listed before neutral ones, so
  a contributing input such as the farmer's own storage answer is never truncated
  out of view.
- **Confidence** is `not_calibrated` everywhere, in words, by construction.

## Honest states

| Situation | What is shown |
| --- | --- |
| No provider key / provider down | "No official record is available for this crop in your district right now (api_key_not_configured). AGRIQ shows no estimated price." |
| No stored records at all | "No official market record is available for this crop and district yet." |
| No crop cycle registered | "Register a crop cycle to see market intelligence for your crop." |
| Too little history for a forecast | Explicit refusal naming the observation counts and repeating the district/state scope |
| Demand requested | "The configured official source publishes prices, not arrival quantities, so no demand figure is produced." |
| Quantity known, costs missing | Row shows gross value plus `NET_VALUE_INCOMPLETE` with the missing components |
| Nothing entered in the sale details | "Enter the quantity you plan to sell to see a gross value. AGRIQ does not estimate yield, so it cannot fill this in." |
| Invalid cost or quantity (negative, or zero quantity) | 400 with the exact field reason, shown verbatim: "quantity_quintals must be greater than zero." |
| Only a price and a storage class | `INSUFFICIENT_DATA` — no forced WAIT |
| Service degradation | "Market intelligence is not available right now." (no figures) |

## Where the data comes from

- **Prices** — AGMARKNET via data.gov.in, fetched server-side through the
  existing Phase 1 market service and stored unmodified with source, retrieval
  time and a duplicate-guarding record hash.
- **History** — those same stored rows. It is never backfilled or interpolated,
  so a young deployment honestly reports a thin history.
- **Risk** — the farmer's stored Phase 5 run (read-only, never recomputed here).
- **Weather / soil / crop cycle** — the existing shared farmer context.
- **Crop and district reference** — the curated AGRIQ catalogs.
- **Costs and quantity** — the farmer's own figures only (rate or total freight,
  input cost, market fee, quantity). AGRIQ holds no freight or input-cost source
  and never fills these in; a supplied freight total takes precedence over
  rate × distance, with `transport_cost_basis` recording which applied.

Demand/arrivals, freight rates, market coordinates, yields and input costs are
**not** available from any verified source and are therefore never shown or
estimated. See `docs/market-data-sources.md`.

## Privacy and ownership

Market intelligence belongs to the authenticated farmer: a foreign field or crop
cycle is indistinguishable from a missing one (404), every route requires the
session, POST routes require the CSRF token, and the provider key is server-side
only — the evidence endpoint is asserted in tests not to leak key material or
even the key's environment-variable name.

## Accessibility

Decision and trend states are text labels (`Sell now`, `trend unavailable`), not
colour alone; the panel body is `aria-live="polite"` with `aria-busy` set while
loading; action buttons are real buttons with visible labels and are disabled
during a request; motion respects the existing reduced-motion rules.
