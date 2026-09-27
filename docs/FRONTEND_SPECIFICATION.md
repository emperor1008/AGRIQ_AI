# AGRIQ AI — Frontend Specification

## Non-negotiable design rule

During the structure refactor, do not change the existing visual design, layout, logo opening, color combination, motion, cards, icon rail, mobile navigation, Farmer mode, Student/Research mode, map, LeafScan card or assistant placement. Only relocate frontend code safely.

## Existing design language to preserve

- Brand: AGRIQ AI — Smart Agriculture, Brighter Tomorrows.
- Tone: premium, optimistic, calm, agricultural intelligence.
- Main visual system: mint/seafoam background, deep leaf-green type, bright lime action accents, white glass-like cards, light grid/doodle details.
- Motion: subtle entrance/splash and hover transitions; respect `prefers-reduced-motion`.
- Layout: desktop left icon rail; mobile bottom navigation; responsive card grid.

## Asset structure after refactor

```text
apps/web/static/
├── css/            # tokens, base, components, dashboard, animations, responsive
├── js/             # app, api-client, assistant, dashboard, map, weather, leafscan, pwa
├── images/agriq-ai-logo.png
├── icons/
├── manifest.json
└── sw.js
```

Jinja templates (base, auth, dashboard, components) live in
`apps/api/agriq/templates/` and reference the assets above via `url_for('static', ...)`,
with the Flask static folder pointed at `../../web/static`.

## Component consistency rules

| Component | Rule |
|---|---|
| Buttons | Existing green rounded visual style; clear loading/disabled states |
| Cards | Existing white/mint premium card style; preserve border radius and shadows |
| Inputs | Large touch-friendly controls, readable labels, visible focus state |
| Alerts | Color + plain-language label; never rely on color alone |
| Source labels | Display provider name, timestamp and unavailable/stale state |
| Image upload | Explain allowed formats and that LeafScan is screening, not confirmed diagnosis |
| Assistant | Keep one conversation entry point; show loading, failure and source states |

## Responsive requirements

- Usable from 320 px mobile width to desktop.
- Minimum 44 px touch targets.
- No horizontal scrolling.
- Forms remain usable with on-screen keyboard.
- Map and cards stack cleanly on mobile.
- Font size remains readable without browser zoom.

## Integration contract

| UI feature | Endpoint/service | Expected result |
|---|---|---|
| Login/register | `POST /login` | Redirect or safe validation error |
| Mode selection | `POST /choose-mode` | Farmer or Student workspace |
| Farm analysis | `POST /dashboard` | Rendered explainable analysis or unavailable state |
| Assistant | `POST /ask-ai` + CSRF header | `{ok, answer, sources}` or clear 503 |
| Weather refresh | `GET /api/live-weather` | weather console + risk forecast or 503 |
| Logout | `POST /logout` + CSRF | Redirect to login |
| Farming Techniques | `GET /farming-techniques` (+ `?category,&crop,&region,&evidence,&q,&mode,&lang,&page`) | Verified cards, facets, pagination, or the honest unavailable state |
| Technique / pesticide detail | `GET /farming-techniques/{technique\|pesticide}/<slug>` | Structured detail with evidence, sources and freshness |
| Filter refresh | `GET /farming-techniques/partials/results` | Re-rendered results region (server-rendered markup, no JSON interpolation) |
| Language choice | `language_switcher()` GET form with `?lang=` | Same page in en/or/hi, filters preserved, choice persisted |

### Farming Techniques UI (Phase 7.2)

Added **inside** the existing shell — same `.side-rail`, `.topbar`, `.glass`,
`.data-panel`, `.pill`, `.link-button`, `.dropdown-card` and token variables. One new
entry (📖) appears in `side_rail()` for **both** Farmer and Student Mode; no existing
card, module, button or route was removed or restyled.

The page is server-rendered first (works without JavaScript and prints the honest
state); `farming-techniques.js` only refreshes the results region when filters change
and degrades to a normal form submit if the fetch fails. Search and filters are plain
labelled form controls; the language switcher is a labelled `<select>` inside a GET
form with a `<noscript>` submit button and hidden inputs that carry the reader's
active filters. Evidence level and freshness are always written as text next to their
colour, never by colour alone. Every page shows a draft-translation notice while the
selected interface language is an unreviewed translation.

## Accessibility requirements

- Semantic labels for inputs and image upload.
- Logo image has meaningful alternative text.
- Keyboard-visible focus state.
- Error messages announced and placed near the failed input.
- Animations reduce/stop when the OS requests reduced motion.
- Odia text renders correctly with selected font fallbacks.

