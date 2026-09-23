# Voice Architecture (Phase 3)

The voice layer is an **input/output interface over the existing Phase 2 Farm Copilot** — never a separate assistant. All intelligence, ownership, knowledge retrieval and safety guardrails remain in the Copilot pipeline.

## Request pipeline

```
Browser                        AGRIQ server                        Providers
───────                        ────────────                        ─────────
language + mic consent
record & preview (WebM/Opus)
   │
voice-recorder.js ── multipart upload ──► voice.py (blueprint)
                                          │ auth + CSRF + rate limit
                                          ▼
                                  audio_validation_service   (decode, limits, silence check)
                                          ▼
                                  voice_orchestrator         (consent → status flow)
                                          ▼
                                  transcription_service ───► SpeechToTextProvider
                                          ▼                        (Bhashini →
                                  transcript shown; farmer          IndicConformer →
                                  edits & confirms                   Indian-English ASR)
                                          │
                                  POST .../confirm ──► POST .../ask
                                          ▼
                                  copilot_orchestrator (Phase 2)  — unchanged
                                          ▼
                                  answer text (+ stored message)
                                          ▼
                                  speech_synthesis_service ─► TextToSpeechProvider
                                          ▼                        (Bhashini → Indic-TTS →
                                  UI: text + audio playback         device fallback, labelled)
```

## Provider abstraction

- `integrations/speech/provider.py` — `SpeechToTextProvider` protocol: `is_configured`, `supports_language`, `transcribe`, `health_check`, `provider_metadata`.
- `integrations/tts/provider.py` — `TextToSpeechProvider` protocol with the same shape plus `synthesise`.
- `integrations/translation/` — Bhashini translation and IndicTrans2 adapters behind one provider interface.

Standard result contracts (see `docs/VOICE_API.md`): confidence carries `available/value/source`; when the provider does not return confidence, `available` is `false` and **no value is inferred**. TTS duration is the **actual decoded** duration, never estimated from text length.

Provider selection follows the mandated evaluation order (Bhashini if configured → IndicConformer → validated Indian-English ASR). Capabilities are computed from real configuration — nothing is hardcoded to available.

## Server modules

| Module | Responsibility |
| --- | --- |
| `services/voice_orchestrator.py` | Session lifecycle: consent → upload → transcription → confirm → Copilot → synthesis; status transitions; retention enforcement. |
| `services/audio_validation_service.py` | Real decoded validation (format/size/duration/sample-rate/channels), silence & corruption detection, private random storage. |
| `services/transcription_service.py` | Provider invocation, timing capture, confidence passthrough. |
| `services/speech_synthesis_service.py` | Answer → speakable text rules (unit expansion, no secrets/JSON), provider call, expiry tracking. |
| `services/translation_service.py` | Optional provider translation; never translates chemical/crop names blindly. |
| `services/language_service.py` | `or` / `hi` / `en-IN` validation and normalisation. |
| `services/voice_consent_service.py` | Versioned consent, revocation, evaluation-use gate. |
| `services/agricultural_vocabulary.py` | Versioned term registry (crops, varieties, stages, pests, districts) for display/search suggestions ("Did you mean: Brown Plant Hopper?"). Never silently rewrites transcripts. |

## Storage & data

Tables: `voice_consents`, `voice_sessions`, `transcripts`, `synthesised_audio` (migration `0003_phase3_voice`). Raw + corrected transcripts stored separately. Audio lives in private `VOICE_TEMP_STORAGE_PATH` with random keys; deleted post-transcription unless retention is explicitly enabled.

## Browser modules (`apps/web/static/js/`)

`voice-recorder.js` (MediaRecorder, timer, preview/delete), `voice-upload-queue.js` (offline queue, retry, progress), `transcript-review.js` (edit/confirm), `audio-player.js` (playback of synthesised answers), `voice-accessibility.js` (labels, focus, reduced-motion, status announcements — never colour-only status). No provider keys or calls exist in browser code.

## Failure behaviour

Any provider failure degrades to the **text interface** with honest messaging; the written answer always precedes audio. See `docs/VOICE_API.md` for the exact user-facing strings.
