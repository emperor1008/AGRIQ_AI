# Risk Intelligence — Product Overview (Phase 5)

The Crop Risk panel gives farmers a screening view of field risk conditions,
computed from the same verified data that powers the rest of AGRIQ AI.

## What the farmer sees

For the active field, five risk cards:

1. **Disease-conducive weather** — conditions favourable to disease
   development (never a diagnosis).
2. **Heavy rain / waterlogging** — forecast rainfall screening and drainage
   guidance.
3. **Heat stress** — temperature screening against crop/stage-aware limits.
4. **Water stress** — dry-spell screening modulated by the field's irrigation
   reality.
5. **Market price movement** — descriptive spread of official AGMARKNET
   records (only when the official source is configured and returns data).

Each card shows: status badge (text + colour, never colour alone), one clear
recommended action, an expandable "Why this assessment?" list, evidence with
source and freshness, confidence in words (Low / Moderate / Higher), and —
when warranted — an expert-confirmation note. Below every actionable card the
farmer can record **Will do / Did it / Not now / Need help**.

## Honest states

| Situation | What is shown |
| --- | --- |
| No elevated risk | "No elevated risk detected from the latest verified data." |
| Weather provider down | Card shows "There is not enough verified data available…" and confidence is null |
| Crop not rice/tomato | "Data unavailable" with the reason recorded, never extrapolated advice |
| Fewer than 3 recent official market records | "Insufficient data" — no synthetic prices |
| Stale weather | Freshness label ("stale") plus reduced confidence |
| First visit | Quiet empty state with a Refresh analysis button |

## Where the data comes from

- **Weather** — Open-Meteo live call for the field's real stored coordinates,
  snapshot-cached; provider name, observation time and retrieval time travel
  with every assessment.
- **Crop & stage** — the farmer's own crop cycle, including the existing
  crop-stage calculation and any farmer-confirmed stage.
- **Field context** — irrigation type, soil type, recent farmer observations.
- **Market** — official AGMARKNET (data.gov.in) records fetched through the
  existing market service; never estimated, never forecast.
- **Image evidence** — the latest completed crop-image screening is attached
  as supporting evidence only, never treated as a diagnosis.

## Privacy and ownership

Risk analyses belong to the authenticated farmer: a foreign field or
assessment id is indistinguishable from a missing one (404). Routes require
the session and CSRF token; ownership tests with two independent farmers
prove no cross-user leakage.

## Accessibility

Status is communicated by text labels, not colour alone; badges carry
`role="status"`; the panel body is `aria-live="polite"`; controls have
visible labels; motion respects `prefers-reduced-motion`.
