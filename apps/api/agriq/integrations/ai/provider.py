"""AI provider abstraction (Phase 2 §1).

``provider.py`` is the seam between the copilot orchestrator and the actual
model integration. The contract is deliberately narrow:

- ``generate()`` receives the prompt payload and returns either a successful
  ``ProviderResult`` or an explicit *unavailable* result.
- No scripted, canned or deterministic fallback text may ever be returned as
  a successful generation. If the provider is not configured, times out or
  errors, the result is unavailable and the copilot surfaces that state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Protocol


@dataclass
class ProviderResult:
    """Outcome of one generation request."""

    available: bool
    text: Optional[str] = None
    provider: str = "gemini"
    model: Optional[str] = None
    error_category: Optional[str] = None   # not_configured|timeout|api_error|invalid_response
    reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "provider": self.provider,
            "model": self.model,
            "error_category": self.error_category,
            "reason": self.reason,
        }


class AIProvider(Protocol):
    """Minimal protocol every AI integration must satisfy."""

    def is_configured(self) -> bool:  # pragma: no cover - trivial
        ...

    def generate(self, prompt: str, *, system: str | None = None) -> ProviderResult:
        ...


__all__ = ["ProviderResult", "AIProvider"]
