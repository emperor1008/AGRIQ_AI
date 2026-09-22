"""Authentication service (registration + login).

Security behaviour per ``03_SECURITY_AND_ACCESS.md``:
- scrypt password hashing.
- Generic failure messages; no account enumeration.
- Duplicate registration returns a generic conflict.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.logging import get_logger
from ..core.text import clean_text
from ..repositories.user_repository import UserRepository

logger = get_logger("services.authentication")

MAX_CONTACT_LENGTH = 120
MAX_PASSWORD_LENGTH = 128
MIN_PASSWORD_LENGTH = 8


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    message: str
    user_contact: str | None = None


def register(contact_raw: str | None, password_raw: str | None) -> AuthResult:
    """Register a new user; generic conflict on duplicates."""
    contact = clean_text(contact_raw, MAX_CONTACT_LENGTH).lower()
    password = str(password_raw or "")

    if not contact or "@" not in contact and not contact.isdigit():
        return AuthResult(False, "Enter a valid email or phone number.")
    if len(password) < MIN_PASSWORD_LENGTH:
        return AuthResult(False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        return AuthResult(False, "Password is too long.")

    if UserRepository.get_by_contact(contact) is not None:
        logger.info("register_conflict")
        return AuthResult(False, "Registration failed. Contact may already be registered.")

    UserRepository.create(contact, password)
    logger.info("register_ok")
    return AuthResult(True, "Registration successful. Please sign in.", user_contact=contact)


def authenticate(contact_raw: str | None, password_raw: str | None) -> AuthResult:
    """Verify credentials; identical message for unknown contact or bad password."""
    contact = clean_text(contact_raw, MAX_CONTACT_LENGTH).lower()
    password = str(password_raw or "")
    if not contact or not password:
        return AuthResult(False, "Invalid contact or password.")

    user = UserRepository.get_by_contact(contact)
    if user is None or not user.check_password(password):
        logger.info("auth_failed")
        return AuthResult(False, "Invalid contact or password.")

    logger.info("auth_ok")
    return AuthResult(True, "Signed in.", user_contact=user.contact)


__all__ = ["AuthResult", "register", "authenticate"]
