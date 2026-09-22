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

## Accessibility requirements

- Semantic labels for inputs and image upload.
- Logo image has meaningful alternative text.
- Keyboard-visible focus state.
- Error messages announced and placed near the failed input.
- Animations reduce/stop when the OS requests reduced motion.
- Odia text renders correctly with selected font fallbacks.

