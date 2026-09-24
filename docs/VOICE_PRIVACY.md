# Voice Privacy (Phase 3)

This document explains exactly how AGRIQ AI handles voice recordings, transcripts and related metadata.

## Data inventory

| Data | Stored where | Purpose | Retention |
| --- | --- | --- | --- |
| Audio recordings | `VOICE_TEMP_STORAGE_PATH` (private, random names, never under public static) | Transcription only | **Default: deleted immediately after transcription.** Retained only when the farmer explicitly enables retention for a session; then removed after `VOICE_AUDIO_RETENTION_HOURS` (default 0 = no retention) or session expiry, whichever is first. |
| Raw transcript | `transcripts.raw_transcript` | Showing the farmer what was heard | Until the user deletes the conversation. |
| Farmer-corrected transcript | `transcripts.corrected_transcript` | Submission to the Farm Copilot | Same as above. |
| Provider confidence | `transcripts.provider_confidence` | Display only ("Confidence not provided." when absent) | Same as above. |
| Consent record | `voice_consents` | Proving lawful processing | Kept; revocation timestamped, never erased. |
| Synthesised audio | `synthesised_audio` (private storage) | Playing back the answer | Removed after `expires_at` (auto-cleanup job) or user deletion. |

Storage keys are random server-generated identifiers — no farmer-controllable filenames, no path traversal.

## Consent

- Before the **first** voice use the farmer sees a consent notice covering: audio may be sent to the configured speech provider, why, retention default (off), how to delete, transcript storage, and whether data may be used for evaluation.
- Versioned consent is stored in `voice_consents` (`consent_version`, `consented_at`).
- Revocation is one control (revoke voice consent) and takes effect immediately: no new recording can be processed.
- Separate explicit flag (`evaluation_use_allowed`) is required before any audio or transcript could ever be used for evaluation. **Default: false.**

## What is never done

- No audio or transcript is used for model training without separate explicit consent.
- No farmer's audio or history personalises another farmer's answers.
- No public URLs expose recordings; playback always requires authentication and ownership.
- Raw audio is never logged; logs record session IDs and status only.
- Provider API keys and raw provider request payloads are never stored in the database.

## Provider processing

- When a cloud provider (e.g. Bhashini) is configured, audio is sent to that provider for transcription only. Processing location is the provider's own region; see `docs/VOICE_DATA_PROVENANCE.md` for the configured provider at any time.
- Local-model providers (IndicConformer / IndicTTS) process audio on the AGRIQ server itself.
- If no provider is configured, voice features report an unavailable state and text input remains fully functional.

## User controls

- Delete a recording: `DELETE /api/v1/voice/sessions/{id}/audio` (immediately removes the file and marks the session `deleted`).
- Refuse retention: `retain_audio` defaults to `false` on every session.
- Revoke consent: voice endpoints refuse processing after revocation; already-deleted audio stays deleted.

## Last reviewed

2026-09-23 — Phase 3 implementation.
