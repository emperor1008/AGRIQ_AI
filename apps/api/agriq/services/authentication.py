"""Authentication service (registration + login) — Phase 7.1 hardened.

Security behaviour per ``03_SECURITY_AND_ACCESS.md``:

- scrypt password hashing (Werkzeug default; never MD5/SHA1/plain SHA-256).
- Generic failure text: an unknown contact and a wrong password are
  indistinguishable to the caller, and the *same* code path is taken.
- Account status is checked inside the service, not patched over in the route.
- A registration request must repeat the password; the two values are compared
  server-side before any row is written.
- Structured :class:`AuthResult.code` values let the API layer respond precisely
  without leaking whether an account exists.
- Failures are logged as security events with no credential material.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.audit import audit_event
from ..core.constants import (
    AUTH_ACCOUNT_DISABLED,
    AUTH_DUPLICATE_ACCOUNT,
    AUTH_GENERIC_FAILURE_MESSAGE,
    AUTH_INVALID_CREDENTIALS,
    AUTH_OK,
    AUTH_PASSWORD_MISMATCH,
    AUTH_VALIDATION,
    AUTH_WEAK_PASSWORD,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
)
from ..core.logging import get_logger
from ..core.text import clean_text
from ..repositories.user_repository import UserRepository
from ..schemas.auth import is_valid_contact

logger = get_logger("services.authentication")

MAX_CONTACT_LENGTH = 120

#: Passwords made of a single repeated/near-trivial pattern are refused even
#: when long enough. Kept short and documented rather than scoring-based: a real
#: strength meter would need a breach corpus AGRIQ does not ship.
_TRIVIAL_PASSWORDS = {
    "password", "password1", "password123", "passw0rd", "12345678", "123456789",
    "1234567890", "qwertyuiq", "qwerty123", "iloveyou", "admin123", "letmein1",
    "welcome1", "agriq123", "agriqai123",
}


@dataclass(frozen=True)
class AuthResult:
    """Outcome of a registration/login attempt (never carries secrets)."""

    ok: bool
    message: str
    user_contact: str | None = None
    code: str = AUTH_VALIDATION


def password_problem(password: str, contact: str) -> str | None:
    """Return a farmer-facing problem description, or None when acceptable.

    Shared with password recovery so registration and reset enforce one policy.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return "Password is too long."
    lowered = password.lower()
    if lowered in _TRIVIAL_PASSWORDS:
        return "That password is too easy to guess. Choose something less common."
    if len(set(password)) <= 2:
        return "That password repeats too few characters. Use a stronger one."
    if lowered == contact.lower():
        return "Your password must not be the same as your email or phone number."
    return None


def register(
    contact_raw: str | None,
    password_raw: str | None,
    password_confirm_raw: str | None = None,
) -> AuthResult:
    """Register a new user; generic conflict on duplicates.

    ``password_confirm_raw`` is required and must match: the form has always sent
    it, and ignoring it (as the pre-7.1 code did) would silently create an
    account whose password the farmer never actually typed correctly.
    """
    contact = clean_text(contact_raw, MAX_CONTACT_LENGTH).lower()
    password = str(password_raw or "")

    if not is_valid_contact(contact):
        return AuthResult(False, "Enter a valid email or phone number.", code=AUTH_VALIDATION)
    confirm = str(password_confirm_raw or "")
    if not confirm:
        return AuthResult(False, "Repeat your password to create the account.", code=AUTH_VALIDATION)
    if confirm != password:
        logger.info("register_password_mismatch")
        audit_event("register_rejected", reason="password_mismatch")
        return AuthResult(False, "The two passwords do not match.", code=AUTH_PASSWORD_MISMATCH)

    problem = password_problem(password, contact)
    if problem:
        audit_event("register_rejected", reason="weak_password")
        return AuthResult(False, problem, code=AUTH_WEAK_PASSWORD)

    if UserRepository.get_by_contact(contact) is not None:
        logger.info("register_conflict")
        audit_event("register_conflict")
        return AuthResult(
            False,
            "Registration failed. That contact may already be registered — "
            "sign in instead, or recover the password.",
            code=AUTH_DUPLICATE_ACCOUNT,
        )

    UserRepository.create(contact, password)
    logger.info("register_ok")
    audit_event("register_ok", contact=contact)
    return AuthResult(
        True, "Registration successful. Please sign in.", user_contact=contact, code=AUTH_OK
    )


def authenticate(contact_raw: str | None, password_raw: str | None) -> AuthResult:
    """Verify credentials and account status.

    The message for an unknown contact, a wrong password and a disabled account
    is identical for the first two; a disabled account is only named *after* its
    password has been verified, so nothing is revealed to someone who cannot
    already authenticate.
    """
    contact = clean_text(contact_raw, MAX_CONTACT_LENGTH).lower()
    password = str(password_raw or "")
    if not contact or not password:
        return AuthResult(False, AUTH_GENERIC_FAILURE_MESSAGE, code=AUTH_INVALID_CREDENTIALS)

    user = UserRepository.get_by_contact(contact)
    if user is None or not user.check_password(password):
        logger.info("auth_failed")
        audit_event("login_failure", contact=contact, reason="invalid_credentials")
        return AuthResult(False, AUTH_GENERIC_FAILURE_MESSAGE, code=AUTH_INVALID_CREDENTIALS)

    if not user.is_active:
        logger.info("auth_failed reason=account_disabled")
        audit_event("login_failure", user_id=user.id, reason="account_disabled")
        return AuthResult(
            False,
            "This account is disabled. Contact the AGRIQ administrator.",
            code=AUTH_ACCOUNT_DISABLED,
        )

    logger.info("auth_ok")
    return AuthResult(True, "Signed in.", user_contact=user.contact, code=AUTH_OK)


def change_password(user, current_password: str, new_password: str, confirm: str) -> AuthResult:
    """Change a verified user's password and revoke their other sessions."""
    from ..core.security import revoke_all_sessions

    if not user.check_password(current_password):
        audit_event("password_change_rejected", user_id=user.id, reason="bad_current_password")
        return AuthResult(False, AUTH_GENERIC_FAILURE_MESSAGE, code=AUTH_INVALID_CREDENTIALS)
    if new_password != confirm:
        return AuthResult(False, "The two passwords do not match.", code=AUTH_PASSWORD_MISMATCH)
    problem = password_problem(new_password, user.contact or "")
    if problem:
        return AuthResult(False, problem, code=AUTH_WEAK_PASSWORD)

    UserRepository.set_password(user, new_password)
    revoke_all_sessions(user.id, "password_change")
    audit_event("password_changed", user_id=user.id)
    return AuthResult(True, "Password updated. Please sign in again.", code=AUTH_OK)


__all__ = ["AuthResult", "register", "authenticate", "change_password", "password_problem"]
