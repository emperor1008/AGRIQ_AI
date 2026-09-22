"""Shared domain result wrappers for external-provider data.

Every integration result that originates from an external provider carries
explicit provenance metadata so the UI can show source, timestamp and
freshness. Nothing in this project fabricates values when a provider is
unavailable: the unavailable state is returned as data instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ProviderUnavailable:
    """Typed marker for a failed/missing external provider response."""

    provider: str
    reason: str = "unavailable"

    def as_dict(self) -> dict[str, Any]:
        return {"available": False, "provider": self.provider, "reason": self.reason}


@dataclass(frozen=True)
class Provenance:
    """Source metadata attached to every external-data payload."""

    provider: str
    fetched_at: str | None = None
    live: bool = False
    extra: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "provider": self.provider,
            "live": self.live,
        }
        if self.fetched_at:
            payload["fetched_at"] = self.fetched_at
        if self.extra:
            payload.update(dict(self.extra))
        return payload


__all__ = ["ProviderUnavailable", "Provenance"]
