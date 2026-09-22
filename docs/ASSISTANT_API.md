# Assistant API (Phase 2)

Base URL: same origin as the app. All state-changing calls require the
session cookie and the `X-CSRF-Token` header (or `csrf_token` form field).
`user_id` is always taken from the session — requests never supply it.

## POST /api/v1/copilot/messages

One personalised copilot turn.

Request:

```json
{
  "conversation_id": "optional existing conversation uuid",
  "field_id": 25,
  "crop_cycle_id": 41,
  "question": "Should I irrigate my rice field today?",
  "language": "or"
}
```

- `language`: `en` | `hi` | `or` (default `en`)
- `field_id` / `crop_cycle_id` must belong to the caller; a foreign id is a
  404 that does not reveal existence.
- Query parameter `response_mode=compact` switches to the low-bandwidth
  payload.

Full response: see docs/FARM_COPILOT.md §Response contract.

Compact response:

```json
{
  "ok": true,
  "conversation_id": "…",
  "answer": "…",
  "action": "Inspect field moisture before irrigating",
  "reasons": ["…", "…", "…"],
  "data_freshness": "live",
  "warning": "Expert confirmation is advised for this guidance.",
  "follow_up": "Record what you did and what you saw in your field timeline.",
  "recommendation_id": 12
}
```

Error states (honest, farmer-friendly):

- No farmer profile → 400 `context_unavailable`
- Foreign field/cycle → 404
- Gemini unavailable → 200 with `answer` =
  "The AI assistant is temporarily unavailable." and full evidence/confidence
  still populated from verified data.

## GET /api/v1/copilot/conversations/{conversation_id}

Owner-only conversation history (last 50 messages: role, content,
timestamps, evidence sources JSON).

## POST /api/v1/recommendations/{id}/feedback

```json
{
  "status": "completed",
  "helpfulness": 4,
  "farmer_note": "I checked the field and irrigation was not needed.",
  "outcome": "No visible water stress after two days."
}
```

- `status`: `planned` | `completed` | `skipped` | `needs_help` (required)
- `helpfulness`: optional 1–5
- Ownership enforced: another user's recommendation id is a 404.
- The original recommendation and evidence are never modified.

## GET /api/v1/recommendations/{id}

Owner-only structured recommendation (action, reasons, evidence, confidence,
validity window, expert flag).

## Legacy endpoints (unchanged)

- `POST /ask-ai` — still serves Student/Research mode via the original
  contract (`{question, context}` → `{answer, source}`), still rate-limited
  and still honest about Gemini availability.
- `GET /api/live-weather`, `GET /api/farmer-context`,
  `GET /api/market-prices`, `GET /healthz` — as documented in Phase 1.

## Rate limits

- Copilot messages: `AGRIQ_RATE_ASSISTANT` (default 12/min per IP)
- ask-ai: same limit
- All limits are server-side; 429 responses never leak internals.
