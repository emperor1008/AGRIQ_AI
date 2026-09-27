"""Auth request schemas: contact + password validation."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.text import clean_text

CONTACT_MAX = 120
PASSWORD_MAX = 128

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\d{10}$")


@dataclass(frozen=True)
class Credentials:
    contact: str
    password: str

    @property
    def valid_contact(self) -> bool:
        return bool(_EMAIL_RE.match(self.contact) or _PHONE_RE.match(self.contact))


def parse_credentials(contact_raw: str | None, password_raw: str | None) -> Credentials:
    """Normalise a contact/password pair with length limits."""
    return Credentials(
        contact=clean_text(contact_raw, CONTACT_MAX).lower(),
        password=str(password_raw or "")[:PASSWORD_MAX],
    )


def is_valid_contact(contact: str | None) -> bool:
    """True for an acceptable email address or 10-digit Indian mobile number.

    Single source of truth shared by registration, login and password recovery,
    so those three can never disagree about what a valid contact is.
    """
    value = clean_text(contact, CONTACT_MAX).lower()
    if not value:
        return False
    return bool(_EMAIL_RE.match(value) or _PHONE_RE.match(value))


__all__ = ["Credentials", "parse_credentials", "is_valid_contact"]
