# packages/shared

Cross-cutting constants and types shared between the API app and future
frontend tooling (or additional services).

```text
shared/
├── constants/   # e.g. mode names, district keys, provider labels
└── types/       # shared TypeScript definition stubs for future tooling
```

The Flask application currently keeps its constants in
`apps/api/agriq/core/constants.py` (single-process deployment). When a
second consumer appears (e.g. a Node build pipeline or a Farm Copilot
worker), promote the shared values here and import from both sides.
