# Security Controls (Phases 1–3)

## Authentication & sessions

- Password hashing (werkzeug `generate_password_hash`); no plain-text storage.
- Session cookies: `HttpOnly`, `SameSite=Lax`, `Secure` in production; environment-only `AGRIQ_SECRET_KEY`.
- POST-only logout; login rate-limited; generic authentication errors (no user enumeration).
- Structured audit logging of auth events — never secrets or raw credentials.

## Authorization / ownership

- Every farmer-owned resource read/write goes through ownership-scoped repositories; a foreign resource is indistinguishable from a missing one (**404**, never 403) so existence is never leaked.
- User identity always comes from the authenticated session — no browser-supplied user IDs.
- Proven by automated tests with at least two users per isolation scenario.

## Request protection

- CSRF tokens on all state-changing routes (forms and JSON headers).
- Flask-Limiter rate limits: login, assistant/copilot, voice upload/transcription/TTS.
- `MAX_CONTENT_LENGTH` caps request size.
- Security headers (CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy) set in the factory.

## Uploads

- **Images (LeafScan/crop images):** JPEG/PNG/WebP allowlist, actual decoded-format verification (never extension/MIME trust), decompression-bomb pixel cap, configurable size limit, EXIF stripped from processed copies, orientation normalised, random storage names, private storage (never public static), automatic temp cleanup.
- **Audio (voice):** decoded-content validation of format, duration, sample rate, channels; size/duration limits; decoder timeout; random storage keys; private storage; deletion after transcription when retention is off.
- **Soil reports:** private storage, type/size validation.

## Secrets & logging

- All secrets from environment only (`.env` git-ignored; `.env.example` documents names, never values).
- No API keys in frontend JavaScript; provider calls are server-side only.
- Logs never contain raw audio, full private transcripts, passwords, tokens or provider payloads.

## Data-layer

- SQLAlchemy ORM with bound parameters — no string-concatenated SQL.
- Migrations are additive; no farmer data is dropped or rewritten.
- Unique constraints prevent duplicate official market records.

## Verified by tests

Ownership isolation (multi-user), CSRF enforcement, rate limits, upload validation (malformed/bomb/mislabeled files), consent gating, security headers, generic auth errors, session fixation resistance. See `apps/api/tests/`.

## Known accepted limitations

- Malware scanning (ClamAV or equivalent) not wired in this build — documented as a deployment recommendation.
- Single-instance rate-limit storage (`memory://`) in development; production must configure Redis (`RATELIMIT_STORAGE_URI`).
