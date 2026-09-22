"""Structured audit logging for security-relevant events.

Audit events never include secrets, passwords, tokens or API keys — only
stable identifiers (user id, resource id, outcome, source IP). Events are
emitted to the ``agriq.audit`` logger so they can be shipped to a sink
without touching application logs.
"""
from __future__ import annotations

import logging

from .time import utc_now

_audit_logger = logging.getLogger("agriq.audit")


def audit_event(event: str, **fields: object) -> None:
    """Emit one structured audit record.

    Example: ``audit_event("farm_create", user_id=12, farm_id=5, outcome="ok")``
    """
    parts = [f"event={event}", f"at={utc_now().isoformat()}"]
    for key, value in fields.items():
        if value is None:
            continue
        rendered = str(value)
        # Defence in depth: never let a secret-like field slip into the log.
        if any(marker in key.lower() for marker in ("password", "secret", "token", "key")):
            rendered = "[redacted]"
        parts.append(f"{key}={rendered}")
    _audit_logger.info(" ".join(parts))


__all__ = ["audit_event"]
