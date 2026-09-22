"""Assistant request schema."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .common import context_value, question_value


@dataclass(frozen=True)
class AssistantRequest:
    question: str
    context: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not self.question


def parse_assistant_request(payload: Mapping[str, Any] | None) -> AssistantRequest:
    payload = payload or {}
    return AssistantRequest(question=question_value(payload), context=context_value(payload))


__all__ = ["AssistantRequest", "parse_assistant_request"]
