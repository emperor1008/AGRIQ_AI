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


__all__ = ["Credentials", "parse_credentials"]
