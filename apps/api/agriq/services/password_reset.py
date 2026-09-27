"""Password recovery service (Phase 7.1).

Flow implemented here (``§13``):

    request → validate contact → issue single-use token (hashed, expiring)
            → real email delivery via :mod:`services.email_provider`
            → user opens link → password policy check
            → consume token → store new scrypt hash → revoke every session

Deliberate behaviour:

- Unknown contacts receive the *same* acknowledgement as known ones, and no
  token is issued for them, so the endpoint cannot be used to enumerate accounts.
- When no email provider is configured the request returns
  ``PASSWORD_RESET_EMAIL_UNAVAILABLE`` and **no** token is created — nothing is
  recorded, nothing is claimed, no password is touched.
- A delivery failure is reported as a failure. It is never rendered as "check
  your inbox".
- Raw tokens exist only in the outgoing message and are never logged or stored.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core.audit import audit_event
from ..core.constants import (
    AUTH_INVALID_RESET_TOKEN,
    AUTH_OK,
    AUTH_PASSWORD_MISMATCH,
    AUTH_WEAK_PASSWORD,
    PASSWORD_RESET_EMAIL_UNAVAILABLE,
    PASSWORD_RESET_REQUEST_ACK_MESSAGE,
    PASSWORD_RESET_TTL_MINUTES,
)
from ..core.logging import get_logger
from ..core.security import revoke_all_sessions
from ..core.text import clean_text
from ..repositories.password_reset_repository import PasswordResetRepository
from ..repositories.user_repository import UserRepository
from ..schemas.auth import is_valid_contact
from . import email_provider
from .authentication import MAX_CONTACT_LENGTH, password_problem

logger = get_logger("services.password_reset")

RESET_PATH = "/reset-password"


@dataclass(frozen=True)
class ResetRequestResult:
    ok: bool
    message: str
    code: str
    delivered: bool = False


@dataclass(frozen=True)
class ResetResult:
    ok: bool
    message: str
    code: str


def request_reset(contact_raw: str | None, *, config, address: str | None = None) -> ResetRequestResult:
    """Issue and deliver a reset link, or report exactly why that is impossible."""
    if not email_provider.is_configured(config):
        audit_event("password_reset_unavailable", reason="email_provider_not_configured")
        return ResetRequestResult(
            False,
            email_provider.unavailable_message("password_reset"),
            PASSWORD_RESET_EMAIL_UNAVAILABLE,
        )

    contact = clean_text(contact_raw, MAX_CONTACT_LENGTH).lower()
    if not is_valid_contact(contact):
        # Same acknowledgement shape, no work performed.
        return ResetRequestResult(True, PASSWORD_RESET_REQUEST_ACK_MESSAGE, AUTH_OK)

    user = UserRepository.get_by_contact(contact)
    if user is None or not user.is_active:
        # No token, no email, identical message: no account enumeration.
        audit_event("password_reset_requested", reason="unknown_or_inactive")
        return ResetRequestResult(True, PASSWORD_RESET_REQUEST_ACK_MESSAGE, AUTH_OK)

    base_url = email_provider.public_base_url(config)
    if not base_url:
        audit_event("password_reset_unavailable", reason="public_base_url_not_configured")
        return ResetRequestResult(
            False,
            "Password recovery is not available on this deployment: the public base URL "
            "is not configured, so a reset link cannot be built. No message was sent.",
            PASSWORD_RESET_EMAIL_UNAVAILABLE,
        )

    _, raw_token = PasswordResetRepository.issue(
        user.id, ttl_minutes=PASSWORD_RESET_TTL_MINUTES, address=address,
        salt=str(config.get("SECRET_KEY", ""))[:32],
    )
    link = f"{base_url}{RESET_PATH}?token={raw_token}"
    body = (
        "AGRIQ AI — password reset\n\n"
        f"A password reset was requested for your AGRIQ AI account ({user.contact}).\n"
        f"Open this single-use link within {PASSWORD_RESET_TTL_MINUTES} minutes:\n\n"
        f"{link}\n\n"
        "If you did not request this, ignore this message: the link expires on its "
        "own and your current password keeps working.\n\n"
        "— AGRIQ AI (automated message, do not reply)"
    )
    delivery = email_provider.send(
        config, to=user.contact, subject="AGRIQ AI password reset", body=body
    )
    if not delivery.sent:
        audit_event("password_reset_delivery_failed", user_id=user.id, status=delivery.status)
        return ResetRequestResult(
            False,
            "The reset message could not be sent, so your password is unchanged. "
            "Please try again later or contact the AGRIQ administrator.",
            delivery.status,
        )

    audit_event("password_reset_requested", user_id=user.id)
    return ResetRequestResult(True, PASSWORD_RESET_REQUEST_ACK_MESSAGE, AUTH_OK, delivered=True)


def confirm_reset(raw_token: str | None, new_password: str | None, confirm: str | None) -> ResetResult:
    """Consume a reset token and replace the password, revoking all sessions."""
    row = PasswordResetRepository.get_by_token(raw_token)
    if row is None or not row.is_usable():
        audit_event("password_reset_failed", reason="invalid_or_expired_token")
        return ResetResult(
            False,
            "That reset link is invalid, already used, or has expired. Request a new one.",
            AUTH_INVALID_RESET_TOKEN,
        )

    user = UserRepository.get_by_id(row.user_id)
    if user is None or not user.is_active:
        audit_event("password_reset_failed", reason="unknown_or_inactive_user")
        return ResetResult(
            False,
            "That reset link is invalid, already used, or has expired. Request a new one.",
            AUTH_INVALID_RESET_TOKEN,
        )

    password = str(new_password or "")
    if password != str(confirm or ""):
        return ResetResult(False, "The two passwords do not match.", AUTH_PASSWORD_MISMATCH)
    problem = password_problem(password, user.contact or "")
    if problem:
        return ResetResult(False, problem, AUTH_WEAK_PASSWORD)

    if not PasswordResetRepository.consume(row):
        return ResetResult(
            False,
            "That reset link is invalid, already used, or has expired. Request a new one.",
            AUTH_INVALID_RESET_TOKEN,
        )

    UserRepository.set_password(user, password)
    revoked = revoke_all_sessions(user.id, "password_reset")
    logger.info("password_reset_completed")
    audit_event("password_reset_completed", user_id=user.id, sessions_revoked=revoked)
    return ResetResult(
        True,
        "Your password has been updated and every other signed-in device was signed out. "
        "Sign in with the new password.",
        AUTH_OK,
    )


__all__ = ["ResetRequestResult", "ResetResult", "request_reset", "confirm_reset"]
