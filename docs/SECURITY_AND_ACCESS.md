# AGRIQ AI — Security and Access Document

## Authentication

Current MVP: contact identifier plus password with scrypt/werkzeug hashing. Session cookies must be HttpOnly, SameSite=Lax and Secure under HTTPS. Do not claim phone/email ownership until OTP/email verification is implemented.

## Roles

| Role | Access |
|---|---|
| Guest | Login and registration page only |
| Authenticated user | Their own Farmer or Student workspace, own future profile/data only |
| Agronomist reviewer (future) | Curated knowledge/model review only; farmer data requires explicit assignment and audit trail |
| Platform admin (future) | Operational configuration and audit tools; no unrestricted reading of farmer records by default |

## Data access rules

- A user can read/write only records whose `user_id`/farmer ownership matches the authenticated session.
- Every farm, field, crop cycle, image, observation, conversation and recommendation query must filter by owner.
- Server authorises ownership; hiding a UI button is not authorisation.
- Images must use private object storage URLs, not public guessable paths.
- Never return provider keys, database URLs, stack traces or internal diagnostics to the browser.

## Required protections

- CSRF protection for every state-changing browser request.
- Rate limits: login 8/minute, assistant 12/minute, dashboard analysis 20/minute, weather 30/minute per IP/user as appropriate.
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

## Edge cases

- Slow/unstable network: timeout, retry-safe UI, preserve user input.
- Duplicate registration: generic conflict response.
- Empty/oversized/malformed form: validate server-side.
- Expired session: return login instruction, not an application error.
- Provider returns malformed response: fail closed and log provider error.
- Mobile upload interrupted: no partial image record and no fabricated result.
- Offline: display cached data only with timestamp and stale label.

## Pre-launch security gates

1. Add email/phone verification and recovery.
2. Run dependency scan, SAST, secret scan and manual OWASP review.
3. Create privacy notice, consent flow, retention/deletion process and incident response plan.
4. Run load, backup/restore and database access-control tests.

