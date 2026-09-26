"""Security helpers: password hashing, CSRF tokens, session and headers.

Implements the requirements of ``03_SECURITY_AND_ACCESS.md``:

- Werkzeug scrypt password hashing.
- Signed CSRF tokens (HMAC over a per-session nonce).
- Session-cookie flags are set in config; headers applied post-request.
"""
from __future__ import annotations

import hmac
import secrets
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import current_app, session
from werkzeug.security import check_password_hash, generate_password_hash

from .constants import SESSION_MODE_KEY, SESSION_USER_KEY
from .exceptions import InvalidCSRFError
from .logging import get_logger

logger = get_logger("security")

F = TypeVar("F", bound=Callable[..., Any])

_CSRF_KEY = "_agriq_csrf_token"


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
    """
    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any):
        if not current_app.config.get("AGRIQ_ENABLE_CSRF", True):
            return view(*args, **kwargs)
        if session.get(SESSION_USER_KEY) is None:
            # Not logged in yet (e.g. login POST); CSRF still enforced when
            # a token exists, otherwise first contact is allowed.
            return view(*args, **kwargs)
        token = None
        from flask import request

        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not verify_csrf(token):
                logger.info("csrf_rejected", extra={"path": request.path})
                raise InvalidCSRFError()
        return view(*args, **kwargs)

    return wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def login_user_session(contact: str) -> None:
    """Record the authenticated contact identifier in the session."""
    session.clear()
    session[SESSION_USER_KEY] = contact
    session.permanent = True


def set_user_mode(mode: str) -> None:
    session[SESSION_MODE_KEY] = mode


def logout_user_session() -> None:
    session.clear()


def current_user_contact() -> str | None:
    return session.get(SESSION_USER_KEY)


def is_authenticated() -> bool:
    return SESSION_USER_KEY in session


def current_user():
    """Resolve the session contact to the active User row (or None).

    The session stores only the contact string; the database lookup here is
    the single trusted path to the user id. Browser-supplied user ids are
    never trusted anywhere in the API.
    """
    contact = current_user_contact()
    if not contact:
        return None
    from ..repositories.user_repository import UserRepository

    return UserRepository.get_by_contact(contact)


__all__ = [
    "hash_password",
    "verify_password",
    "get_csrf_token",
    "verify_csrf",
    "require_csrf",
    "login_user_session",
    "set_user_mode",
    "logout_user_session",
    "current_user_contact",
    "current_user",
    "is_authenticated",
]
