"""Conversation service (Phase 2 §14): structured conversation memory.

Owns conversation lifecycle and memory selection for the copilot. The safe
context builder selects only relevant, ownership-verified records and never
sends the farmer's entire history to the model.
"""
from __future__ import annotations

from typing import Any, Optional

from ..core.logging import get_logger
from ..repositories.copilot_repository import ConversationRepository

logger = get_logger("services.conversation")

# How many recent turns are eligible for the prompt (kept small intentionally;
# COPILOT_MAX_CONTEXT_TOKENS bounds the final size).
MEMORY_TURNS = 6


def get_or_create_conversation(user_id: int, mode: str,
                               conversation_ref: Optional[str | int] = None):
    """Return an owned conversation for the ref, or create a new one.

    A conversation ref that belongs to another user is treated as not found
    (a new conversation is created) — cross-user reuse is impossible.
    """
    if conversation_ref:
        conversation = ConversationRepository.get_owned(conversation_ref, user_id)
        if conversation is not None:
            return conversation, False
        logger.info("conversation_ref_not_owned_new_created user_id=%s", user_id)
    return ConversationRepository.create(user_id=user_id, mode=mode), True


def record_turn(conversation_id: int, user_message: str, assistant_message: str,
                sources: dict[str, Any] | None = None) -> tuple[int, int]:
    """Persist both sides of one turn; returns (user_message_id, assistant_message_id)."""
    user_msg = ConversationRepository.add_message(conversation_id, "user", user_message)
    assistant_msg = ConversationRepository.add_message(
        conversation_id, "assistant", assistant_message, sources=sources
    )
    return user_msg.id, assistant_msg.id


def conversation_memory(conversation_id: int) -> list[dict[str, str]]:
    """Recent turns of *this* conversation, oldest first, trimmed."""
    messages = ConversationRepository.recent_messages(conversation_id, limit=MEMORY_TURNS)
    memory: list[dict[str, str]] = []
    for message in messages:
        if message.role not in ("user", "assistant"):
            continue
        memory.append({"role": message.role, "content": (message.content or "")[:500]})
    return memory


__all__ = ["get_or_create_conversation", "record_turn", "conversation_memory", "MEMORY_TURNS"]
