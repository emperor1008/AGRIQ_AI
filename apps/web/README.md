# AGRIQ AI — Web (frontend assets)

This directory holds every browser-delivered asset. It is intentionally
static-only: no build step, no framework — matching the original UI 1:1.

## Layout

```text
web/
├── static/
│   ├── css/
│   │   ├── tokens.css        # design tokens ( colours, shadows ) — values frozen
│   │   ├── base.css          # doodle background, html/body, layout primitives
│   │   ├── components.css    # glass cards, inputs, buttons, map, tables, chat
│   │   ├── dashboard.css     # farmer/student dashboards, weather + treatment consoles
│   │   ├── animations.css    # motion rules + prefers-reduced-motion guard
│   │   └── responsive.css    # launchers, dropdown cards, patch media queries
│   ├── js/
│   │   ├── app.js            # bootstrap: reads AgriqBoot, wires modules
│   │   ├── api-client.js     # fetch helpers (CSRF header injection)
│   │   ├── assistant.js      # chat panel
│   │   ├── dashboard.js      # student form sync, calculators, smooth anchors
│   │   ├── map.js            # Leaflet GeoRisk map
│   │   ├── weather.js        # live weather console
│   │   ├── leafscan.js       # upload guard + demo case
│   │   └── pwa.js            # service-worker registration
│   ├── images/               # logo and imagery
│   ├── icons/                # PWA icons
│   ├── manifest.json         # PWA manifest
│   └── sw.js                 # service worker (static cache-first)
└── README.md
```

## Rules

- **Do not change colours, selectors or visual values here** — the CSS was
  split mechanically from the original `style.css` and recombines
  byte-identically.
- The server injects `window.AgriqBoot = { mapData, userMode,
  studentDomainConfig, ... }` before `app.js` runs.
- All new JS must be plain, dependency-free ES2017 consistent with the
  existing modules.
