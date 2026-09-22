# AGRIQ AI Voice Architecture (Phase 3)

The voice layer is an **input/output interface over the existing Farm
Copilot** — not a separate assistant. Every agricultural decision still
flows through the Phase 2 orchestration pipeline, Shared Farmer Context
and approved knowledge retrieval. Voice adds: audio capture → validated
transcription → farmer-confirmed transcript → the same copilot → TTS
playback of the written answer.

Status: **implemented as described here; evaluation not yet validated**
(see docs/VOICE_EVALUATION.md).

## Pipeline

```
Farmer selects language (or / hi / en-IN)
  → microphone permission (browser)
  → record (MediaRecorder, timer, preview)
  → POST /api/v1/voice/sessions                 (consent-gated)
  → POST /api/v1/voice/sessions/{id}/audio      (server-side validation)
  → GET  /api/v1/voice/sessions/{id}/transcription (ASR, never fabricates)
  → farmer reviews/edits transcript
  → POST /api/v1/voice/sessions/{id}/confirm    (confirmed transcript stored
                                                 separately from raw)
  → POST /api/v1/voice/sessions/{id}/ask        → EXISTING copilot_orchestrator
  → written answer (always visible)
  → POST /api/v1/voice/synthesise               (TTS of farmer-facing text)
  → GET  /api/v1/voice/audio/{audio_id}         (owner-only streaming)
```

## Module map

| Layer | Module | Responsibility |
|---|---|---|
| API | `agriq/api/voice.py` | HTTP only: auth, CSRF, parsing, serialisation |
| Service | `services/voice_orchestrator.py` | Pipeline state machine, provider selection, circuit breaker |
| Service | `services/audio_validation_service.py` | Real decoding, magic-byte checks, duration/measurement, private storage |
| Service | `services/voice_consent_service.py` | Consent gate, retention decision, revocation |
| Service | `services/language_service.py` | Closed set {or, hi, en-IN}; never claims more |
| Service | `services/agricultural_vocabulary.py` | Display-aid suggestions (“Did you mean …?”) |
| Integration | `integrations/speech/*` | ASR providers behind one contract |
| Integration | `integrations/tts/*` | TTS providers behind one contract |
| Integration | `integrations/translation/*` | Translation providers behind one contract |
| Repository | `repositories/voice_repository.py` | Owner-scoped persistence (get_owned everywhere) |
| Domain | `models/voice.py` + migration 0003 | voice_consents, voice_sessions, transcripts, synthesised_audio |

## Provider abstraction

Every ASR provider implements (`integrations/speech/provider.py`):

- `is_configured()`, `supports_language(code)`, `transcribe(audio, code)`,
  `health_check()`, `provider_metadata()`

Every TTS provider implements the mirrored contract
(`integrations/tts/provider.py`). Providers **never invent values**: an
unconfigured or failing provider returns `status="unavailable"` with an
error category; missing confidence stays `{"available": False, "value":
None, "source": None}`. Confidence is stored verbatim from the provider —
never derived from transcript length.

Implemented providers (evaluation order):

1. **Bhashini ASR/TTS/translation** — used only when `BHASHINI_API_KEY`
   etc. are configured.
2. **AI4Bharat IndicConformer ASR** (Odia/Hindi) — used only when local
   model paths are configured.
3. **Indian-English ASR model** — used only when a model path is configured.
4. **Device TTS** — metadata only; synthesis is browser-side and explicitly
   labelled a fallback.

With nothing configured, all capabilities honestly report
`asr_available: false / tts_available: false` and text input remains the
primary path. **No provider is bundled or enabled by default.**

## Honesty rules enforced in code

- ASR failure → `"We could not reliably understand this recording. Please
  try again or type your question."` — never a scripted transcript.
- TTS failure → written answer stays; `"Audio playback is currently
  unavailable."` — never an empty audio file.
- Session state records the **actual** provider and model used.
- Policy pin: when `VOICE_ASR_PROVIDER` is set, no silent provider
  switching occurs.
- Circuit breaker: 3 consecutive ASR failures open a 2-minute cool-down.

## Data model

- `voice_sessions` tracks status
  `created → uploaded → processing → transcript_ready → transcript_confirmed
  → copilot_completed`, or `failed / expired / deleted`.
- `transcripts` keeps `raw_transcript` and `corrected_transcript`
  separately with `correction_confirmed_at`.
- `synthesised_audio` rows expire after the configured TTL; files live in
  private storage (`VOICE_TEMP_STORAGE_PATH`), never under static/.

## Retention

Audio is retained only when **both** the farmer consented to retention
and the session explicitly asked for it (`retain_audio`, default false).
Sessions expire after 24 h; the sweep (`cleanup_expired`) flips expired
sessions and drops their audio. See docs/VOICE_PRIVACY.md.
