# Voice Evaluation (Phase 3)

## Current status

**"Voice feature evaluation is in progress."**

No real evaluation has been performed yet, therefore this document intentionally contains **no accuracy numbers, WER/CER figures, latency measurements or intelligibility scores**. Fabricating any of these would violate the AGRIQ real-data policy (see `docs/AI_SAFETY.md`).

## What exists today

- Provider-contract unit tests with clearly-labelled synthetic test fixtures (test directories only).
- Integration tests proving consent gating, ownership isolation, retention behaviour and honest failure states.
- `GET /api/v1/voice/capabilities` reflecting **actual** provider configuration, never hardcoded capability claims.

## Evaluation protocol (defined, not yet executed)

### Dataset requirements

- Consented recordings from real speakers of Odia, Hindi and Indian English.
- Multiple genders and age groups where consent permits; multiple microphones/device categories.
- Quiet and realistic farm-background conditions.
- Real agricultural queries: district, crop, variety, pest and operation terminology.
- **Human-verified reference transcripts** for every sample.

### Metadata recorded per sample

Anonymous speaker ID, language, district/region, device category, environment category, duration, consent status, human-verified transcript, provider/model version, evaluation date. **Never** name, phone number or unnecessary identity.

### Metrics to calculate (only from reviewed samples)

Word Error Rate, Character Error Rate, agricultural-term accuracy, district-name accuracy, crop/variety-name accuracy, transcript-correction rate, failed-transcription rate, median latency, P95 latency, TTS intelligibility (human review), task-completion rate.

### Reporting rules

- Metrics reported **separately** per language (Odia / Hindi / Indian English), per environment (quiet / noisy) and per device category.
- Controlled-condition and field-condition results never merged into one number.
- Until sufficient reviewed samples exist, the UI shows: **"Voice feature evaluation is in progress."**
- No percentages may be displayed anywhere until real evaluation data exists.

## Test fixtures vs evaluation data

Synthetic audio under `tests/` exists only to exercise code paths. It is never called a farmer recording, never counted in accuracy results and never mixed with evaluation datasets.
