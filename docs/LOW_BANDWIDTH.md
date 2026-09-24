# Low-Bandwidth Behaviour (Phases 2–3)

AGRIQ targets rural Odisha connectivity. This document describes how the app degrades gracefully on slow or intermittent networks.

## Copilot compact mode

`POST /api/v1/copilot/messages?response_mode=compact` returns a trimmed payload: one recommended action, 2–3 reasons, data freshness, one warning/limitation and a follow-up step. No images, minimal JSON.

## Voice upload queue (`voice-upload-queue.js`)

- Recordings captured offline stay **locally queued** in the browser with explicit consent and are labelled **"Queued — will send when connected."** They are never marked transcribed or processed.
- Uploads retry up to `VOICE_QUEUE_MAX_RETRIES` with idempotent session submission (re-POSTing an uploaded session does not duplicate work).
- Progress indicator, cancel and delete-before-upload controls are provided.
- Nothing is ever fabricated for a queued recording: no transcript, no confidence, no status other than queued.

## Data discipline

- Cached capability/status responses carry an expiry; stale data is labelled stale, never live.
- Weather and market panels show *"Verified data is currently unavailable."* rather than stale values presented as current.
- Clear offline indicator in the UI; text input always remains functional.
- Compact payloads first; large assets load lazily.

## Service worker

The PWA service worker caches app shell assets for offline load but **never caches API responses** — answers, weather and prices always come from the network or show an explicit unavailable state.
