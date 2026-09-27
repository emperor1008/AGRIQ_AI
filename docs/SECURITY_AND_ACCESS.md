# AGRIQ AI — Security and Access Document

## Authentication

Contact identifier (email or 10-digit mobile) plus password, hashed with scrypt
(Werkzeug default, `scrypt:32768:8:1`). Session cookies are HttpOnly,
SameSite=Lax and Secure under HTTPS. Phone/email ownership is **not** claimed
until a real OTP/email provider is configured.

### Sessions (Phase 7.1)

- The cookie carries an opaque token; the server stores only its SHA-256 digest
  in `user_sessions` and requires a **live row** on every authenticated request.
  A signed cookie alone is not proof of identity.
- Idle window `AGRIQ_SESSION_IDLE_TIMEOUT_HOURS` (8h, refreshed by activity) and a
  hard cap `AGRIQ_SESSION_ABSOLUTE_TIMEOUT_HOURS` (720h) that never extends.
- Logout revokes the row *before* clearing the cookie, so a copied cookie is
  worthless afterwards. Password change/reset revokes every session.
- Cookie-only sessions issued before Phase 7.1 are deliberately not adopted:
  they cannot be revoked, so the user signs in again.

### Authentication vs authorization

`get_current_user()` (`core/security.py`) is the single authentication
dependency: no session or a revoked/expired row → `401 AUTH_UNAUTHORIZED`, a
disabled account → `401 AUTH_ACCOUNT_DISABLED`. Every protected route resolves
the identity through it, so "who is the user?" has exactly one implementation.
Cross-user access to a resource that exists stays `404` (no enumeration).

### Password recovery (Phase 7.1)

Single-use, SHA-256-hashed, 30-minute reset tokens; all sessions are revoked on
completion. Delivery uses real SMTP only. **With no email provider configured
the endpoints answer `PASSWORD_RESET_EMAIL_UNAVAILABLE` and send nothing** — an
unavailable provider is never reported as a sent message. Email verification is
not required by the current architecture and is not simulated.

### Rate limiting

| Route group | Limit |
|---|---|
| `POST /login` (sign-in **and** registration) | 8/minute per IP |
| `POST /forgot-password`, `POST /reset-password` | 5/minute per IP |
| `/api/v1/auth/*` (session management) | authenticated + CSRF |

There is deliberately **no account lockout**: a permanent or easily triggered
lock would let an attacker deny service to a real farmer (§16). Throttling is
per-address, time-limited and logged, and never reveals whether an account
exists.

## Roles

| Role | Access |
|---|---|
| Guest | Login and registration page only |
| Authenticated user | Their own Farmer or Student workspace, own future profile/data only |
| Agronomist reviewer (operator, Phase 7.2) | Approves/rejects knowledge records **through the CLI only** with `--reviewer "<name>"`; an anonymous approval is refused. No HTTP route can insert or approve knowledge, so there is no remotely reachable reviewer surface to authenticate. |
| Platform admin (future) | Operational configuration and audit tools; no unrestricted reading of farmer records by default |

### Agricultural knowledge access (Phase 7.2)

* Every Farming Techniques page and `/api/v1/farming-techniques*` route requires an
authenticated session (`get_current_user()`); unauthenticated pages redirect to
`/login`, unauthenticated APIs answer `401 AUTH_UNAUTHORIZED`.
* Knowledge records are **canonical shared content, not user-owned**: there is no
per-user object to enumerate, so IDOR does not apply to them. The feature never
accepts a user, farm or field id from the client.
* The visibility gate is a server-side double condition — record
`review_status == VERIFIED` **and** its `knowledge_sources.review_status` approved.
`PENDING_REVIEW`, `REJECTED` and expired regulatory records are never serialised; an
unknown or unverified slug answers 404 without revealing that it exists.
* Ingestion is local-file only and validates provenance before writing: https-only
URL shape, no credentials in the URL, no loopback/private hosts, no
`javascript:`/`data:`, organisation allow-list, evidence/category/region vocabulary,
preparation and application status vocabulary. **No URL from user input is ever
fetched** — there is no runtime SSRF surface in this feature.
* `POST /api/v1/farming-techniques/ask` refuses manufacturing/synthesis, recipe and
dosage intent (English, Hindi, Odia) and otherwise returns only reviewed passages
with their sources. It never calls a language model and never invents a quantity.

## Data access rules

- A user can read/write only records whose `user_id`/farmer ownership matches the authenticated session.
- Every farm, field, crop cycle, image, observation, conversation and recommendation query must filter by owner.
- Server authorises ownership; hiding a UI button is not authorisation.
- Images must use private object storage URLs, not public guessable paths.
- Never return provider keys, database URLs, stack traces or internal diagnostics to the browser.

## Required protections

- CSRF protection for every state-changing browser request, including the login
  and logout POSTs (the token the page issued must come back).
- Rate limits: login 8/minute, password recovery 5/minute, assistant 12/minute,
  dashboard analysis 20/minute, weather 30/minute per IP/user as appropriate.
- Origin allow-list (`AGRIQ_ALLOWED_ORIGINS`): empty means same-origin only;
  `*` is refused at startup. AGRIQ ships no CORS middleware, so no credentialed
  cross-origin API exists by default.
- Upload allowlist: JPEG, PNG, WebP; 5 MiB maximum; decode safely; strip/reject unsafe files.
- Input normalization, length limits and district/crop allowlists.
- CSP, `X-Frame-Options: DENY`, `nosniff`, referrer policy, HSTS only under HTTPS.
- Passwords never logged or returned.
- Secrets only in local `.env`/deployment secrets.

## Failure behaviour

| Failure | User-facing response | Server action |
|---|---|---|
| Invalid password | “Invalid contact or password.” | Log generic auth event; no account enumeration |
| Missing/invalid CSRF | “Invalid or missing CSRF token.” | Return 400 |
| Weather provider down | “Live weather is temporarily unavailable.” | Return typed unavailable result; no fake values |
| Gemini unavailable | “Assistant is temporarily unavailable.” | Return 503; no scripted answer presented as Gemini |
| Market feed unavailable | “Official mandi data is unavailable.” | Show source and retry option |
| Bad image | “Use a clear JPG, PNG or WebP under 5 MiB.” | Reject before analysis |
| Unauthorised page/API | Redirect to login or return 401 JSON | Log only necessary security metadata |
| No verified knowledge for a question | `DATA_UNAVAILABLE` / `INSUFFICIENT_REAL_DATA` explained in the reader's language | Return the named state; never a generated answer |
| Preparation/dose not documented | `PREPARATION_DATA_UNAVAILABLE` / `APPLICATION_DATA_UNVERIFIED` | Serve only what the cited source states |
| Asked how to make a pesticide | `KNOWLEDGE_MANUFACTURING_REFUSED` | Refuse; offer safe-use information instead |

## Edge cases

- Slow/unstable network: timeout, retry-safe UI, preserve user input.
- Duplicate registration: generic conflict response.
- Empty/oversized/malformed form: validate server-side.
- Expired session: return login instruction, not an application error.
- Provider returns malformed response: fail closed and log provider error.
- Mobile upload interrupted: no partial image record and no fabricated result.
- Offline: display cached data only with timestamp and stale label.

## Pre-launch security gates

1. Configure a real email provider (`AGRIQ_EMAIL_PROVIDER=smtp` + SMTP settings)
   so password recovery can deliver, then add email/phone *verification* using
   the same token machinery (`services/password_reset.py` is the reference
   implementation; verification must not be faked either).
2. Run dependency scan, SAST, secret scan and manual OWASP review.
3. Create privacy notice, consent flow, retention/deletion process and incident response plan.
4. Run load, backup/restore and database access-control tests.

