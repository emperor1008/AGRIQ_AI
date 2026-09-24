# Voice API (Phase 3)

All voice endpoints are authenticated (session cookie) and ownership-scoped: a resource owned by another farmer is indistinguishable from a missing one (404). CSRF applies to state-changing requests. Rate limits apply to upload, transcription and TTS.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v1/voice/capabilities` | Actual configured ASR/TTS availability per language (`or`, `hi`, `en-IN`). Never hardcoded to true. |
| POST | `/api/v1/voice/sessions` | Start a voice session. Body: `language` (required), `field_id`, `crop_cycle_id`, `retain_audio` (default **false**). |
| POST | `/api/v1/voice/sessions/{id}/audio` | Multipart audio upload. Server validates real decoded content (format, size, duration, sample rate, channels). |
| GET | `/api/v1/voice/sessions/{id}/transcription` | Poll transcription status; returns raw transcript + provider confidence or `"Confidence not provided."` |
| POST | `/api/v1/voice/sessions/{id}/confirm` | Body: `confirmed_transcript`, `language`. Farmer confirms/edits before Copilot submission. |
| POST | `/api/v1/voice/sessions/{id}/ask` | Submits the **confirmed** transcript to the existing Phase 2 Copilot (no duplicated logic). |
| POST | `/api/v1/voice/synthesise` | Body: `message_id`, `language`. Only synthesises messages owned by the authenticated user. |
| DELETE | `/api/v1/voice/sessions/{id}/audio` | Deletes the recording immediately; session marked `deleted`. |

Supporting endpoints (schemas in `agriq/schemas/voice.py`): consent grant/revoke/status.

## Session status flow

```
created → uploaded → processing → transcript_ready → transcript_confirmed
       → copilot_completed
Any step may go to: failed | expired | deleted
```

## Honest-failure contract

- Unclear audio → *"We could not reliably understand this recording. Please try again or type your question."*
- No provider configured / provider down → capabilities report unavailable; text input is the fallback.
- Confidence not returned by provider → `confidence.available = false`, displayed as *"Confidence not provided."* — never inferred.
- Consent missing/revoked → processing refused with a clear farmer-facing message.
- Cross-user access → `404` (existence never leaked).

## Guarantees

- Transcript is **always** farmer-confirmed before Copilot submission.
- Raw and corrected transcripts stored separately, both visible to the owner.
- Provider + model version recorded per session (`voice_sessions.provider`, `provider_model`).
- Audio deleted after transcription when `retain_audio` is false (default).
