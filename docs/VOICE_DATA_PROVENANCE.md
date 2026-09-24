# Voice Data Provenance (Phase 3)

Provenance record for every external or maintained source used by the voice layer. Updated whenever the enabled provider changes.

## Enabled providers (default build)

| Component | Provider | Status in this build | Model version | Licence | Processing location |
| --- | --- | --- | --- | --- | --- |
| Speech-to-text (ASR) | Bhashini (validated for Odia/Hindi), IndicConformer fallback, validated Indian-English ASR | **Not configured** — no API key / model path present, so all ASR reports `asr_available: false` | n/a (recorded per transcription by the provider) | Bhashini: Government of India national-language platform terms; IndicConformer: Apache-2.0 / CC-BY per AI4Bharat model card | Cloud (Bhashini) or on-server (local models) |
| Text-to-speech (TTS) | Bhashini TTS, AI4Bharat Indic-TTS fallback, device-native fallback (explicitly labelled) | **Not configured** — `tts_available: false` | n/a | Bhashini platform terms; Indic-TTS open licence per AI4Bharat model card | Cloud or on-server; device fallback runs in the browser |
| Translation | Copilot's own supported-language responses (primary), Bhashini translation when configured, IndicTrans2 where licence permits | Primary mode active (no separate translation needed for the 3 supported languages) | Copilot prompt version | Platform terms / AI4Bharat open licence | On-server |

Because no speech provider is configured in the default build, `GET /api/v1/voice/capabilities` honestly reports all languages as unavailable rather than pretending. Voice features are progressive enhancement over the fully working text interface.

## Fields used from each provider

- **ASR:** transcript text, provider-declared confidence (or none), detected language, model identifier. Nothing else is persisted; raw provider payloads are discarded.
- **TTS:** synthesised audio bytes, actual decoded duration, audio format, model identifier.
- **Translation:** translated text only.

## Retrieval method

Server-side only, over HTTPS, with `VOICE_PROVIDER_TIMEOUT_SECONDS` timeout, bounded retries (`VOICE_QUEUE_MAX_RETRIES` for queued uploads) and a circuit breaker. No browser JavaScript ever touches provider endpoints or keys.

## Failure behaviour

- ASR failure → *"We could not reliably understand this recording. Please try again or type your question."* Text input unaffected.
- TTS failure → written answer preserved, *"Audio playback is currently unavailable."* No empty audio file is ever produced.
- Confidence absent from provider response → stored/displayed as *"Confidence not provided."* — never inferred or fabricated.

## Data classification

- Farmer recordings and transcripts: **farmer-entered / farmer-derived data**, owned by the farmer.
- Provider transcripts: **observation data produced by the configured provider** for one session; provenance (provider + model + timestamps) stored on `voice_sessions`.

## Known limitations

- No automatic language detection in production (may be offered only as an optional suggestion after real evaluation).
- Only Odia (`or`), Hindi (`hi`) and Indian English (`en-IN`) are supported; no dialect claims.

**Last reviewed:** 2026-09-23.
