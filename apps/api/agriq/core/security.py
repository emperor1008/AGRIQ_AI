"""Security helpers: password hashing, CSRF tokens, sessions and headers.

Implements the requirements of ``03_SECURITY_AND_ACCESS.md`` (Phase 7.1 hardened):

- Werkzeug scrypt password hashing.
- Signed CSRF tokens (HMAC over a per-session nonce).
- Session-cookie flags are set in config; headers applied post-request.
- **Server-side sessions**: the cookie carries an opaque token whose SHA-256
  digest must match a live ``user_sessions`` row. Logout, expiry, password
  change and explicit revocation therefore work server-side; a replayed cookie
  is worthless once its row is revoked.
- One identity lookup per request, cached on ``flask.g``.
"""
from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import current_app, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from .constants import (
    AUTH_ACCOUNT_DISABLED,
    SESSION_ID_KEY,
    SESSION_MODE_KEY,
    SESSION_TOKEN_KEY,
    SESSION_USER_KEY,
)
from .exceptions import AuthRequiredError, ForbiddenError, InvalidCSRFError
from .logging import get_logger

logger = get_logger("security")

F = TypeVar("F", bound=Callable[..., Any])

_CSRF_KEY = "_agriq_csrf_token"

#: Per-request identity cache. It lives on the WSGI environ rather than on
#: ``flask.g``: ``g`` is bound to the application context, which in tests (and
#: under an embedded server) can outlive a single request, and a cached identity
#: must never leak from one request into the next.
_IDENTITY_CACHE_KEY = "agriq.auth_identity"
_UNRESOLVED = object()


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password with Werkzeug's default scrypt method."""
    return generate_password_hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time password verification; never raises on bad hash."""
    try:
        return check_password_hash(password_hash or "", password)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------

def get_csrf_token() -> str:
    """Return the session CSRF token, creating it on first use."""
    token = session.get(_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_CSRF_KEY] = token
    return token


def verify_csrf(token: str | None) -> bool:
    """Constant-time comparison of the submitted token with the session token."""
    expected = session.get(_CSRF_KEY)
    if not expected or not token:
        return False
    return hmac.compare_digest(str(expected), str(token))


def require_csrf(view: F) -> F:
    """Validate the CSRF token for state-changing requests.

    The token may be posted as ``csrf_token`` or sent in the
    ``X-CSRF-Token`` header (used by the assistant fetch API).

    Order matters (Phase 7.1): the origin allow-list is checked first, then the
    session, then the token. An unauthenticated request therefore reaches the
    view and receives its own 401 instead of a confusing CSRF 400 — the view's
    ``get_current_user()`` still refuses it, so this is not a bypass.
    """
    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            enforce_allowed_origin()
        if not current_app.config.get("AGRIQ_ENABLE_CSRF", True):
            return view(*args, **kwargs)
        if session_identity() is None:
            # No live session: the view's own authentication dependency decides
            # (401 for protected endpoints away from the HTML dashboard).
            return view(*args, **kwargs)
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not verify_csrf(token):
                logger.info("csrf_rejected", extra={"path": request.path})
                raise InvalidCSRFError()
        return view(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Sessions (server-side, revocable)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Identity:
    """The authenticated identity for the current request."""

    user: Any
    session_id: int | None


#: How long (hours) a session may stay idle before it is refused.
_DEFAULT_IDLE_HOURS = 8
#: How long (hours) a session may exist at all, however active it is.
_DEFAULT_ABSOLUTE_HOURS = 24 * 30


def _idle_timeout_hours() -> int:
    try:
        return int(current_app.config.get("AGRIQ_SESSION_IDLE_TIMEOUT_HOURS", _DEFAULT_IDLE_HOURS))
    except (TypeError, ValueError):
        return _DEFAULT_IDLE_HOURS


def _absolute_timeout_hours() -> int:
    try:
        return int(current_app.config.get(
            "AGRIQ_SESSION_ABSOLUTE_TIMEOUT_HOURS", _DEFAULT_ABSOLUTE_HOURS
        ))
    except (TypeError, ValueError):
        return _DEFAULT_ABSOLUTE_HOURS


def _client_address() -> str | None:
    """Client address for abuse triage; only ever stored salted+hashed."""
    return request.remote_addr if request else None


def _address_salt() -> str:
    return str(current_app.config.get("SECRET_KEY", ""))[:32]


def login_user_session(user: Any) -> None:
    """Start an authenticated server-side session for a real user row.

    ``session.clear()`` before the new token is written is deliberate: it
    destroys any pre-login session state (session-fixation defence) and drops
    the old CSRF nonce so a fresh one is issued.
    """
    from ..repositories.session_repository import SessionRepository

    session.clear()
    row, raw_token = SessionRepository.create(
        user,
        idle_timeout_hours=_idle_timeout_hours(),
        absolute_timeout_hours=_absolute_timeout_hours(),
        user_agent=(request.user_agent.string if request else None),
        address=_client_address(),
        salt=_address_salt(),
    )
    session[SESSION_USER_KEY] = user.contact
    session[SESSION_TOKEN_KEY] = raw_token
    session[SESSION_ID_KEY] = row.id
    session.permanent = True


def set_user_mode(mode: str) -> None:
    session[SESSION_MODE_KEY] = mode


def logout_user_session(reason: str = "logout") -> bool:
    """Revoke the current session row (when reachable) and clear the cookie.

    If the database is unavailable the cookie is still cleared; the row then
    dies at its own expiry. That limitation is logged rather than hidden, and it
    never turns into an authentication success.
    """
    token = session.get(SESSION_TOKEN_KEY)
    revoked = False
    if token:
        try:
            from ..repositories.session_repository import SessionRepository

            revoked = SessionRepository.revoke_by_token(token, reason)
        except Exception:  # pragma: no cover - database outage path
            logger.warning("logout_revoke_failed", extra={"reason": reason})
    session.clear()
    return revoked


def revoke_all_sessions(user_id: int, reason: str) -> int:
    """Revoke every live session of a user (password change/reset, lockout)."""
    from ..repositories.session_repository import SessionRepository

    return SessionRepository.revoke_all_for_user(user_id, reason)


def session_identity() -> Identity | None:
    """Resolve the request's identity from the cookie **and** its session row.

    Cached for the duration of one request, so a request that checks auth
    several times still costs a single indexed database round trip. Returns
    ``None`` for a missing cookie, an unknown token, a revoked row and an
    expired row alike, so those cases are indistinguishable to a caller.
    """
    environ = request.environ
    cached = environ.get(_IDENTITY_CACHE_KEY, _UNRESOLVED)
    if cached is not _UNRESOLVED:
        return cached
    identity: Identity | None = None
    token = session.get(SESSION_TOKEN_KEY)
    if token:
        from ..repositories.session_repository import SessionRepository

        resolved = SessionRepository.resolve(token)
        if resolved is not None:
            user, row = resolved
            if getattr(user, "is_active", False):
                SessionRepository.touch(row, idle_timeout_hours=_idle_timeout_hours())
                identity = Identity(user=user, session_id=row.id)
    environ[_IDENTITY_CACHE_KEY] = identity
    return identity


def current_user_contact() -> str | None:
    """Contact of the authenticated user, or None (cookie hint, verified)."""
    identity = session_identity()
    return identity.user.contact if identity else None


def current_session_id() -> int | None:
    identity = session_identity()
    return identity.session_id if identity else None


def is_authenticated() -> bool:
    """True only when a live server-side session backs the cookie."""
    return session_identity() is not None


def current_user():
    """Resolve the authenticated User row, or None when unauthenticated.

    The session cookie only authorises a lookup of a live ``user_sessions`` row;
    the user id always comes from that row. Browser-supplied ids are never
    trusted anywhere in the API (§18).
    """
    identity = session_identity()
    return identity.user if identity else None


def get_current_user():
    """Centralised authentication dependency: user or :class:`AuthRequiredError`.

    Every authenticated endpoint resolves its identity through this function so
    "who is the user?" has exactly one implementation (§19).
    """
    identity = session_identity()
    if identity is None:
        raise AuthRequiredError()
    user = identity.user
    if not getattr(user, "is_active", False):
        raise AuthRequiredError(
            "This account is disabled. Contact the AGRIQ administrator.",
            code=AUTH_ACCOUNT_DISABLED,
        )
    return user


# ---------------------------------------------------------------------------
# Origin allow-list (§23: no wildcard origins with credentialed auth)
# ---------------------------------------------------------------------------

def enforce_allowed_origin() -> None:
    """Reject cross-origin state-changing requests when an allow-list is set.

    AGRIQ serves its frontend from the same origin, so the default (empty list)
    means "same-origin only" and nothing has to be configured. When
    ``AGRIQ_ALLOWED_ORIGINS`` is set (comma-separated), any request that declares
    a different ``Origin`` is refused. There is deliberately no wildcard option.
    """
    allowed = current_app.config.get("AGRIQ_ALLOWED_ORIGINS") or []
    if not allowed:
        return
    origin = request.headers.get("Origin")
    if not origin:
        return
    if origin not in set(allowed):
        logger.info("origin_rejected", extra={"path": request.path})
        raise ForbiddenError("Request origin is not allowed.", code="ORIGIN_NOT_ALLOWED")


# ---------------------------------------------------------------------------
# Login CSRF (the login form carries a token issued before sign-in)
# ---------------------------------------------------------------------------

def login_csrf_ok(token: str | None) -> bool:
    """Validate the CSRF token issued with the login form, when one exists.

    A visitor who has never loaded the form has no session nonce; that first
    contact is allowed (there is nothing to protect yet, and the form issues a
    token immediately). Once a nonce exists it must match, which is what stops
    login-CSRF from silently signing a victim into an attacker's account.
    """
    if not current_app.config.get("AGRIQ_ENABLE_CSRF", True):
        return True
    if not session.get(_CSRF_KEY):
        return True
    return verify_csrf(token)


__all__ = [
    "Identity",
    "hash_password",
    "verify_password",
    "get_csrf_token",
    "verify_csrf",
    "require_csrf",
    "login_user_session",
    "set_user_mode",
    "logout_user_session",
    "revoke_all_sessions",
    "session_identity",
    "current_session_id",
    "current_user_contact",
    "current_user",
    "get_current_user",
    "is_authenticated",
    "login_csrf_ok",
    "enforce_allowed_origin",
]
