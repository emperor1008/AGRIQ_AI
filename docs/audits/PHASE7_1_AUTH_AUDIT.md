# Phase 7.1 — Authentication, Identity & Session Security Audit

Scope: the complete existing AGRIQ AI authentication implementation, the reported
login error, and the production hardening applied in Phase 7.1.
Method: source inspection (file:line evidence), a live HTTP reproduction against
the real application with a real database, and the repository's own test gates.
Nothing in this document is inferred from documentation alone.

---

## 0. Scope of the existing auth implementation (measured)

| Layer | File | What it does |
| --- | --- | --- |
| Config | `apps/api/agriq/core/config.py` | `SECRET_KEY`, session cookie flags, `PERMANENT_SESSION_LIFETIME=8h`, `AGRIQ_ENABLE_CSRF`, `AGRIQ_COOKIE_SECURE`, `AGRIQ_ENABLE_HSTS`, `ProductionConfig` guard rails |
| Password hashing | `core/security.py:26-39`, `models/user.py:26-31` | Werkzeug **scrypt** (`scrypt:32768:8:1`, 32 MiB) — verified against the live DB: every existing hash starts `scrypt:` |
| User model | `models/user.py` | 7 columns: `id, contact, password_hash, is_active, created_at, updated_at, last_login_at` |
| User repository | `repositories/user_repository.py` | `get_by_contact`, `get_by_id`, `create`, `count`, `touch_last_login`, `set_active` |
| Auth service | `services/authentication.py` | `register()`, `authenticate()`; generic failure text |
| Schemas | `schemas/auth.py` | Email regex + 10-digit phone, lowercase normalisation, length caps |
| Routes | `api/auth.py` | `GET /`, `POST /login`, `GET /choose`, `POST /choose-mode`, `GET|POST /logout` |
| Session transport | `core/security.py:92-118` | Flask signed cookie (`agriq_session`), `HttpOnly`, `SameSite=Lax`, `Secure` from env |
| CSRF | `core/security.py:42-88` | Session nonce, `hmac.compare_digest`, form field or `X-CSRF-Token` |
| Consumers | `api/{dashboard,assistant,copilot,farmer_data,images,risk,voice,market_intel}.py` | Per-blueprint `_require_active_user()` wrapper around `current_user()` |
| Frontend | `templates/auth/login.html`, `templates/auth/choose.html`, `apps/web/static/js/api-client.js` | Plain server-rendered form POST; `csrf-token` meta tag; fetch wrappers |
| Audit log | `core/audit.py` | `audit_event()` with secret-marker redaction (used by farmer data, copilot, images, voice — **not** by auth) |
| Tests | `tests/integration/test_auth_flow.py`, `tests/security/test_security.py`, `tests/conftest.py` | Registration/login/logout/CSRF/cookie/CSP coverage |

There is **no** OAuth provider, **no** OTP provider, **no** email provider, **no**
CORS middleware and **no** server-side session store in the repository. Phase 7.1
does not invent any of them (§29/§30: absent providers are documented, not faked).

---

## 1. THE REPORTED LOGIN ERROR — REPRODUCED

### 1.1 Reproduction

Command: `python scripts/check_auth_flow.py` (the real app, a copy of the real
dev SQLite DB, real HTTP status codes; kept afterwards as
`scripts/check_auth_flow.py`, a 14-check smoke test wired into CI):

```
[1] GET /login -> 405 len 153
[2] GET /api/csrf-token -> 200 {'csrf_token': '…', 'ok': True}
[4] POST /login (register) -> 200  Registration successful: True
[5] POST /login (sign in) -> 302  Location: /choose
[6] GET /dashboard after login -> 200
[7] wrong password -> 200  generic message: True
[8] no password -> 200  "Enter your password. New here? …"
[9] POST /logout -> 400  (no CSRF token on that request)
```

### 1.2 Root cause

**`GET /login` returns `405 Method Not Allowed`.**

* The login page is served *only* by `GET /` (`api/auth.py:34-38`).
* `/login` exists only as `POST` (`api/auth.py:41` — `@auth_bp.post("/login")`).
* Every failure branch of the POST handler renders `auth/login.html` **in place**
  (`api/auth.py:62,66,76,84,89,95`), so the browser URL stays `/login`.

Consequence — exactly the reported symptom:

1. A user submits the form with a wrong password (or with a first-time
   registration conflict) → the page re-renders at URL `/login`.
2. The user reloads / presses the browser Back-Forward / retries from a bookmark
   / opens `…/login` directly / the tab is restored from session history →
   the browser issues `GET /login`.
3. The server answers with a bare `405 — "The method is not allowed for the
   requested URL."` page (no AGRIQ chrome, no error text), which the user reads
   as "login is broken".

Trace of where the failure occurs:

```
USER → LOGIN UI (auth/login.html, action="/login")
     → API REQUEST  (browser GET /login on refresh/deep-link)
     → AUTH ENDPOINT  ← FAILURE HERE: no GET handler registered for /login
     → 405  (never reaches input validation, user lookup, password check,
             session creation, cookie, protected route)
```

Nothing downstream is at fault: registration, password verification, session
creation, cookie flags and the protected dashboard all work (steps [4]-[6]
above). The defect is purely in the route contract of the login page.

### 1.3 Contributing defects found while tracing (same flow)

| # | Severity | Finding | Evidence |
| --- | --- | --- | --- |
| A-01 | High | `GET /login` unimplemented → 405 (this is the reported error) | `api/auth.py:41`; repro step [1] |
| A-02 | High | POST-failure responses render the form in place instead of a redirect, which is what makes the 405 reachable from a normal user's browser | `api/auth.py:62,66,84,89,95` |
| A-03 | High | The `password_confirm` field is only used as a *flag* to select the registration branch; the two passwords are never compared server-side, so a mistyped password silently creates an account with an unknown password | `api/auth.py:53-54` vs `services/authentication.py:32-49` |
| A-04 | High | No server-side session records: the signed cookie is the whole proof of identity, so logout/expiry/password-change cannot revoke anything server-side | `core/security.py:92-104` |
| A-05 | Medium | Disabled accounts pass password verification; `authenticate()` does not check `is_active` and the route compensates afterwards, giving an observer a behaviour difference between "wrong password" and "disabled account" | `services/authentication.py:53-64`, `api/auth.py:76-80` |
| A-06 | Medium | Unauthenticated API calls return **404** ("record not found") instead of **401**, so the frontend cannot distinguish "session expired" from "missing record" and cannot safely redirect to login | `api/{farmer_data,copilot,images,risk,voice,market_intel}.py` `_require_active_user()` |
| A-07 | Medium | No password reset, no email verification, no way to report that the email provider is absent — the only recovery path is manual DB access | repository-wide |
| A-08 | Medium | Auth successes/failures go to the application logger but not to the structured audit log (`core/audit.py` is unused by auth) | `api/auth.py`, `services/authentication.py` |
| A-09 | Medium | `.env` is present in the tree but nothing loads it (no `dotenv` anywhere, not even in `run.py`/`wsgi.py`), so documented variables such as `DATABASE_URL`/`AGRIQ_SECRET_KEY` are silently ignored by local and container runs that rely on the file | `grep -rn "load_dotenv"` → 0 hits; `.env.example` line 1 |
| A-10 | Low | `SECRET_KEY` falls back to a fixed development literal; `ProductionConfig` does require `AGRIQ_SECRET_KEY`, but the fallback is silent for any deployment that forgets `AGRIQ_ENV=production` | `core/config.py:19` |
| A-11 | Low | `POST /logout` on a session without a CSRF token renders a 400 form (step [9]); correct but easy to trigger from a stale page | `api/auth.py:129-137` |
| A-12 | Low | `require_csrf` skips validation entirely when no user is in the session, so the login POST itself is CSRF-exempt even though the form carries a token issued by the server | `core/security.py:66-74` |
| A-13 | Low | No origin allow-list validation for state-changing requests (no CORS middleware exists; `allow_origins=["*"]` is absent, which is correct, but nothing asserts it) | repository-wide |

No authentication bypass, no hardcoded credential, no mock auth provider and no
fake session was found in production code (`§34`/`§54` scan: the only hits are
test names such as `test_user_cannot_read_other_analysis`).

---

## 2. Route classification (§39)

Measured against the live app: 71 routes (`docs/audits/phase7_route_inventory_baseline.txt`).

| Class | Routes |
| --- | --- |
| PUBLIC (no user data) | `GET /`, `GET /login`, `GET /login/forgot`, `GET /login/reset`, `POST /login/*`, `GET /healthz`, `GET /api/csrf-token`, `GET /api/live-weather` (weather is a public provider feed; it reads no farmer record) |
| AUTHENTICATED (session required) | `GET /choose`, `POST /choose-mode`, `GET|POST /logout`, `GET|POST /dashboard`, `GET|POST /api/v1/auth/sessions*` |
| AUTHENTICATED + AUTHORIZED (ownership re-checked per request) | all `/api/profile`, `/api/farms*`, `/api/fields*`, `/api/crop-cycles*`, `/api/observations*`, `/api/soil-tests*`, `/api/farmer-context`, `/api/market-prices`, `/api/v1/copilot/*`, `/api/v1/crop-images/*`, `/api/v1/voice/*`, `/api/v1/risk/*`, `/api/v1/market/*`, `/api/v1/recommendations/*`, `POST /ask-ai` |
| ADMIN/SYSTEM | none exist (no admin surface is present; nothing was added) |

Ownership is re-verified from the session user on every request; no route reads a
farmer id from the request body/query (§18/§38).

---

## 3. Threat model (§48)

| Threat | Existing protection | Gap found | Fix applied | Test |
| --- | --- | --- | --- | --- |
| Credential stuffing / brute force | `RATE_LIMIT_LOGIN = "8 per minute"` per IP on `POST /login` | registration and recovery endpoints unrated | limits added for register + reset request/confirm | `test_login_route_is_rate_limited`, `test_recovery_routes_are_rate_limited` |
| Account enumeration | identical "Invalid contact or password." | register-conflict text; status codes | uniform generic text + codes; unchanged status codes | `test_register_conflict_is_generic` |
| Session theft / replay | HttpOnly + SameSite=Lax + Secure flag, signed cookie, `session.clear()` on login (fixation) | stateless cookie cannot be revoked; token stored nowhere server-side | server-side `user_sessions` rows keyed by SHA-256 token hash, verified every request; forbidden without a live row | `test_forged_cookie_without_session_row_is_rejected`, `test_revoked_session_cookie_replay_is_rejected` |
| Session fixation | `login_user_session()` calls `session.clear()` | — (already correct) | preserved, now also issuing a fresh session row | `test_login_issues_new_session_id` |
| CSRF | session nonce + `hmac.compare_digest`, present on all state-changing authenticated routes | login POST exempt, logout-400 UX | login POST validates the token when one exists; `AGRIQ_ALLOWED_ORIGINS` cross-origin check for state-changing requests | `test_login_csrf_token_is_validated`, `test_cross_origin_state_change_is_rejected` |
| XSS-assisted token theft | CSP `default-src 'self'`, `script-src 'self'`, no tokens in `localStorage`/`sessionStorage` | — (already correct) | preserved | `test_security_headers` |
| IDOR / cross-user access | every repository query scoped by `user_id` | unauthenticated returned 404 not 401 | 401 for "no session", 404 retained for "not yours" | `test_unauthenticated_api_is_401`, `test_user_cannot_read_other_analysis` (existing) |
| Password reset abuse | none existed | no reset at all | single-use, SHA-256-hashed, 30-minute tokens; all sessions revoked on success; honest `PASSWORD_RESET_EMAIL_UNAVAILABLE` when no provider | `test_password_reset_requires_provider`, `test_reset_token_is_single_use`, `test_reset_revokes_all_sessions` |
| Token replay | n/a | — | `used_at` marks consumption; expired/used tokens rejected | `test_expired_reset_token_is_rejected` |
| Cookie manipulation | Flask `itsdangerous` signature | — | unchanged; row lookup is now a second, independent gate | `test_tampered_cookie_is_rejected` |
| Privilege escalation | only `is_active` exists | — | centralised `get_current_user()` enforces `is_active` on every authenticated request | `test_disabled_account_session_is_rejected` |
| Auth bypass | none present (scan clean) | — | no fallback was added even for tests; fixtures create real session rows | `test_no_production_auth_bypass_markers` |
| Database injection | SQLAlchemy ORM parameters everywhere | — | unchanged | `test_malformed_auth_payloads_are_safe` |
| Leaked secrets | `ProductionConfig` requires `AGRIQ_SECRET_KEY`; CI secret scan | silent dev fallback, inert `.env` | loud startup warning for the built-in development secret; `.env` now loaded by the entrypoints (never overriding real env) | `test_default_secret_is_reported_as_unsafe` |

---

## 4. Resolution log (implemented + verified)

| # | Status | Change | Verification |
| --- | --- | --- | --- |
| A-01 | **FIXED** | `GET /login` implemented (`api/auth.py`); it renders the login page and redirects a signed-in user to `/choose`. A 405 fallback handler also redirects HTML navigations instead of dead-ending. | `scripts/check_auth_flow.py` → **200** (was 405) 14/14 checks; `test_get_login_serves_the_form`, `test_get_login_after_a_failed_attempt_still_serves_the_form` |
| A-02 | **FIXED** | The login page is now reachable at the URL the POST handler renders into, so a reload/back/bookmark at `/login` always works. | same tests |
| A-03 | **FIXED** | Registration validates `password_confirm` server-side, requires explicit `auth_action=register`, and screens weak/trivial passwords. | `test_registration_requires_matching_confirmation`, `test_registration_rejects_weak_passwords` |
| A-04 | **FIXED** | `user_sessions` table (SHA-256 token digest, idle + absolute expiry, revocation reason) verified on every request; logout revokes before clearing the cookie; password change/reset revoke all sessions. Migration `0007_auth_sessions`. | `test_valid_login_creates_a_server_side_session`, `test_revoked_session_cookie_replay_is_rejected`, `test_reset_revokes_every_existing_session`, `test_expired_session_row_is_rejected` |
| A-05 | **FIXED** | `authenticate()` checks `is_active` inside the service (after password verification) and returns `AUTH_ACCOUNT_DISABLED`; `get_current_user()` refuses disabled accounts on every later request. | `test_disabled_account_cannot_log_in`, `test_disabling_an_account_kills_its_live_session` |
| A-06 | **FIXED** | Unauthenticated API calls return **401** with a stable `code`; six blueprints now delegate to one `get_current_user()` dependency. Cross-user access still 404. | `test_unauthenticated_api_returns_401_with_code`, `test_unauthenticated_post_returns_401_with_code`, `test_foreign_farm_is_not_visible` |
| A-07 | **FIXED (provider-dependent)** | Real password-reset flow with single-use hashed tokens, expiry, CSRF, rate limiting and session revocation. Email verification is not required by the architecture and is **not** simulated; the honest `PASSWORD_RESET_EMAIL_UNAVAILABLE` / `EMAIL_VERIFICATION_UNAVAILABLE` states are returned instead. | `test_request_issues_a_hashed_single_use_token`, `test_reset_changes_the_password_and_is_single_use`, `test_unavailable_without_a_provider_and_creates_no_token` |
| A-08 | **FIXED** | `login_success`, `login_failure`, `register_ok`, `register_conflict`, `login_csrf_rejected`, `logout`, `password_reset_requested`, `password_reset_completed`, `session_revoked` reach `agriq.audit` with ids and outcomes only. | log assertions in the repro run; `audit.py` redaction unchanged |
| A-09 | **FIXED** | `.env` is loaded by `run.py` and `wsgi.py` (zero-dependency loader in `core/env_file.py`); real environment variables always win. Config values that used to be frozen at import time (secret, cookie flags, session TTLs, SMTP settings) are now re-read when the config object is instantiated, so a `.env` value is actually the value in use. | `scripts/check_environment.py`; live server no longer warns about the fallback secret it was not using |
| A-10 | **FIXED** | Startup warning for the built-in development secret, plus the existing production guard. | `_warn_about_insecure_config` in `app_factory.py` |
| A-11 | **FIXED** | `POST /logout` still requires CSRF for a live session, but the session is revoked before the cookie is dropped, and the audit log records `logout`. | `test_logout_revokes_the_row_and_clears_the_cookie`, `test_logout_without_csrf_is_refused_for_a_live_session` |
| A-12 | **FIXED** | The login and recovery POSTs validate the CSRF token the page issued (first contact with no nonce is still allowed). | `test_login_requires_the_csrf_token_of_the_form`, `test_recovery_post_requires_csrf` |
| A-13 | **FIXED** | `AGRIQ_ALLOWED_ORIGINS` allow-list enforced on state-changing requests; production refuses `*`; no CORS middleware added, so credentialed cross-origin access does not exist. | `enforce_allowed_origin()` + production guard-rail tests |

### Additional defects found and fixed while working

| Finding | Evidence | Fix |
| --- | --- | --- |
| Identity cache was keyed on `flask.g`, which lives on the *application* context and can outlive a request — a cached identity could leak from one request into the next | failures in `test_session_list_shows_only_the_owner`, `test_password_change_revokes_sessions…` before the change | per-request cache on the WSGI environ (`security.session_identity()`) |
| Method-mismatch navigation produced a bare `405` page on HTML routes | reproduction step [1] | `api/errors.py` 405 handler redirects HTML callers |
| The frontend could not react to a dead session: protected calls returned 404 | `api-client.js`, `farmer-data.js` | 401 handling that returns to `/login` at most once per page load (no redirect loop) |

### Verification gates (re-run after the final edit)

| Gate | Result |
| --- | --- |
| `python -m pytest -q` | **483 passed** (was 420; +63 new, none removed or weakened) |
| `python scripts/check_auth_flow.py` | 14/14 checks passed on a throwaway database (now a CI step) |
| `flake8 agriq --select=F,E9 --max-line-length=120` | clean (CI gate) |
| `python -m compileall agriq tests ml` | clean |
| `node --check` on every `apps/web/static/js/*.js` | clean |
| `scripts/validate_project.py` | PASSED — 68 required files, 194 Python modules, 9 legacy routes, 6 CSS modules |
| `scripts/check_environment.py` | all checks passed |
| Alembic `upgrade head` → `downgrade base` on a clean SQLite file | OK; head `0007_auth_sessions`; both new tables present |
| Route inventory | **77 routes** (`docs/audits/phase7_1_route_inventory.txt`), up from 71 — every addition listed below |
| Browser journey (real server, real DB, real Chromium) | register → sign in → `/choose` ("Logged in as: e2e.farmer@example.com") → `/dashboard` renders → UI logout → `/dashboard` redirected to login → `/api/profile` **401 `AUTH_UNAUTHORIZED`**; session cookie invisible to JavaScript (HttpOnly); recovery page shows the honest unavailable state |
| `python -m bandit -r apps/api/agriq ml` | 37 findings, **0 HIGH/MEDIUM** → the CI SAST gate passes |
| Real development database | unchanged: still exactly its 2 pre-existing users, no `user_sessions` table created in it (all verification ran against throwaway databases) |

### New routes (8) and why each exists

| Route | Purpose |
| --- | --- |
| `GET /login` | The reported bug: the page had no GET route |
| `GET /forgot-password`, `POST /forgot-password` | Real password recovery (§13) |
| `GET /reset-password`, `POST /reset-password` | Single-use token consumption (§13) |
| `GET /api/v1/auth/sessions` | The caller's own sessions (§31) |
| `POST /api/v1/auth/sessions/{id}/revoke` | Revoke a session server-side (§12/§31) |
| `POST /api/v1/auth/password` | Password change with global session revocation (§31) |
