"""Email delivery provider (Phase 7.1).

AGRIQ AI ships **no** email provider of its own: password reset and email
verification require an operator to configure one. Until then this module reports
an explicit unavailable state and refuses to pretend a message was delivered.

Configuration (all read from the environment; nothing is hardcoded):

- ``AGRIQ_EMAIL_PROVIDER``  ``smtp`` to enable real delivery (any other value is
  treated as "not configured").
- ``AGRIQ_SMTP_HOST``, ``AGRIQ_SMTP_PORT`` (default 587)
- ``AGRIQ_SMTP_USERNAME``, ``AGRIQ_SMTP_PASSWORD``
- ``AGRIQ_SMTP_USE_TLS``   ``1`` (default) to STARTTLS, ``0`` to send plain
- ``AGRIQ_EMAIL_FROM``      envelope/from address, defaults to the SMTP username
- ``AGRIQ_PUBLIC_BASE_URL`` public origin used to build links (e.g.
  ``https://agriq.example.org``); without it links are not built at all.

Only the standard library is used, so enabling email does not add a dependency.
Message bodies and tokens are never logged.
"""
from __future__ import annotations

import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from ..core.constants import (
    EMAIL_VERIFICATION_UNAVAILABLE,
    PASSWORD_RESET_EMAIL_UNAVAILABLE,
)
from ..core.logging import get_logger

logger = get_logger("services.email")

PROVIDER_SMTP = "smtp"


@dataclass(frozen=True)
class EmailDelivery:
    """Result of an attempted send — never claims success it cannot prove."""

    sent: bool
    status: str
    message: str
    detail: str | None = None


def _config(source) -> dict:
    get = source.get if hasattr(source, "get") else lambda key, default=None: default
    return {
        "provider": str(get("AGRIQ_EMAIL_PROVIDER", "") or "").strip().lower(),
        "host": str(get("AGRIQ_SMTP_HOST", "") or "").strip(),
        "port": int(get("AGRIQ_SMTP_PORT", 587) or 587),
        "username": str(get("AGRIQ_SMTP_USERNAME", "") or "").strip(),
        "password": str(get("AGRIQ_SMTP_PASSWORD", "") or ""),
        "use_tls": str(get("AGRIQ_SMTP_USE_TLS", "1")).strip().lower() in {"1", "true", "yes", "on"},
        "sender": str(get("AGRIQ_EMAIL_FROM", "") or "").strip(),
        "base_url": str(get("AGRIQ_PUBLIC_BASE_URL", "") or "").strip().rstrip("/"),
    }


def is_configured(source) -> bool:
    """True only when a real provider is both selected and fully specified."""
    cfg = _config(source)
    if cfg["provider"] != PROVIDER_SMTP:
        return False
    return bool(cfg["host"] and (cfg["username"] or cfg["sender"]))


def unavailable_status(purpose: str = "password_reset") -> str:
    """Canonical honest state for the missing provider, per purpose."""
    if purpose == "email_verification":
        return EMAIL_VERIFICATION_UNAVAILABLE
    return PASSWORD_RESET_EMAIL_UNAVAILABLE


def unavailable_message(purpose: str = "password_reset") -> str:
    if purpose == "email_verification":
        return (
            "Email verification is not available on this deployment: no email provider "
            "is configured. No verification message was sent."
        )
    return (
        "Password recovery email is not available on this deployment: no email provider "
        "is configured. No reset message was sent and your password is unchanged."
    )


def public_base_url(source) -> str:
    """Configured public origin for links, or an empty string (not guessed)."""
    return _config(source)["base_url"]


def send(source, *, to: str, subject: str, body: str) -> EmailDelivery:
    """Attempt a real send; report exactly what happened.

    Returns ``sent=False`` with the provider's honest status when email is not
    configured or the SMTP conversation fails. The caller must never translate
    this into a success screen (§47).
    """
    cfg = _config(source)
    if cfg["provider"] != PROVIDER_SMTP:
        return EmailDelivery(False, unavailable_status(), unavailable_message())
    if not cfg["host"]:
        return EmailDelivery(
            False, PASSWORD_RESET_EMAIL_UNAVAILABLE,
            "Email provider is selected but no SMTP host is configured.",
        )
    sender = cfg["sender"] or cfg["username"]
    if not sender:
        return EmailDelivery(
            False, PASSWORD_RESET_EMAIL_UNAVAILABLE,
            "Email provider is selected but no sender address is configured.",
        )

    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=20) as smtp:
            if cfg["use_tls"]:
                smtp.starttls()
            if cfg["username"] and cfg["password"]:
                smtp.login(cfg["username"], cfg["password"])
            smtp.send_message(message)
    except Exception as exc:  # noqa: BLE001 - provider failures must not 500
        # Only the exception class is logged: SMTP errors can echo credentials
        # and the message body contains a single-use token.
        logger.warning("email_send_failed error=%s", type(exc).__name__)
        return EmailDelivery(
            False, "EMAIL_DELIVERY_FAILED",
            "The email provider could not be reached, so no message was sent.",
            detail=type(exc).__name__,
        )

    logger.info("email_sent")
    return EmailDelivery(True, "EMAIL_SENT", "Message accepted by the email provider.")


__all__ = [
    "PROVIDER_SMTP",
    "EmailDelivery",
    "is_configured",
    "unavailable_status",
    "unavailable_message",
    "public_base_url",
    "send",
]
