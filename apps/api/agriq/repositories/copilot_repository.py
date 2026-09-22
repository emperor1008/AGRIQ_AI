"""Ownership-scoped repositories for Phase 2 copilot data.

- KnowledgeRepository: sources + chunks (review-gated reads for retrieval;
  ingestion writes are CLI-only, never a browser route).
- RecommendationRepository gains owned reads + status-aware listing for the
  context builder (previous recommendations and their outcomes).
- FeedbackRepository: feedback rows belong to exactly one user.
- ConversationRepository: conversation-scoped message writes for the
  versioned copilot entry point (user id is always the session user).
"""
from __future__ import annotations

import json
from typing import Any, Optional

from ..extensions import db
from ..models.farmer import Conversation, FarmerAction, Message, Recommendation
from ..models.knowledge import AssistantRun, KnowledgeChunk, KnowledgeSource, RecommendationFeedback


class KnowledgeRepository:
    """knowledge_sources + knowledge_chunks data access."""

    @staticmethod
    def get_by_key(source_key: str) -> Optional[KnowledgeSource]:
        return db.session.execute(
            db.select(KnowledgeSource).where(KnowledgeSource.source_key == source_key)
        ).scalar_one_or_none()

    @staticmethod
    def get(source_id: int) -> Optional[KnowledgeSource]:
        return db.session.get(KnowledgeSource, source_id)

    @staticmethod
    def upsert_source(data: dict[str, Any]) -> KnowledgeSource:
        """Insert or update by source_key (duplicate ingestion prevented)."""
        source = KnowledgeRepository.get_by_key(str(data.get("source_key", "")))
        if source is None:
            source = KnowledgeSource(**data)
            db.session.add(source)
        else:
            for key, value in data.items():
                setattr(source, key, value)
        db.session.commit()
        return source

    @staticmethod
    def approved_sources(crop: str | None = None) -> list[KnowledgeSource]:
        stmt = db.select(KnowledgeSource).where(
            KnowledgeSource.review_status == KnowledgeSource.STATUS_APPROVED
        )
        if crop:
            stmt = stmt.where(db.or_(KnowledgeSource.crop.is_(None), KnowledgeSource.crop.ilike(f"%{crop}%")))
        return list(db.session.execute(stmt).scalars())

    @staticmethod
    def approved_chunks_for_sources(source_ids: list[int]) -> list[KnowledgeChunk]:
        if not source_ids:
            return []
        stmt = (
            db.select(KnowledgeChunk)
            .join(KnowledgeSource, KnowledgeChunk.source_id == KnowledgeSource.id)
            .where(
                KnowledgeChunk.source_id.in_(source_ids),
                KnowledgeSource.review_status == KnowledgeSource.STATUS_APPROVED,
            )
        )
        return list(db.session.execute(stmt).scalars())

    @staticmethod
    def replace_chunks(source_id: int, chunks: list[dict[str, Any]]) -> int:
        """Replace all chunks of a source (re-ingestion is full-refresh)."""
        db.session.execute(
            db.delete(KnowledgeChunk).where(KnowledgeChunk.source_id == source_id)
        )
        for chunk in chunks:
            db.session.add(KnowledgeChunk(source_id=source_id, **chunk))
        db.session.commit()
        return len(chunks)

    @staticmethod
    def count_by_status() -> dict[str, int]:
        rows = db.session.execute(
            db.select(KnowledgeSource.review_status, db.func.count(KnowledgeSource.id))
            .group_by(KnowledgeSource.review_status)
        ).all()
        return {status: int(count) for status, count in rows}


class RecommendationRepository:
    """recommendations + farmer_actions data access scoped by user."""

    @staticmethod
    def create(user_id: int, data: dict[str, Any]) -> Recommendation:
        recommendation = Recommendation(user_id=user_id, **data)
        db.session.add(recommendation)
        db.session.commit()
        return recommendation

    @staticmethod
    def get_owned(recommendation_id: int, user_id: int) -> Optional[Recommendation]:
        recommendation = db.session.get(Recommendation, recommendation_id)
        if recommendation is None or recommendation.user_id != user_id:
            return None
        return recommendation

    @staticmethod
    def recent_for_cycle(cycle_id: int, user_id: int, limit: int = 5) -> list[Recommendation]:
        stmt = (
            db.select(Recommendation)
            .where(
                Recommendation.crop_cycle_id == cycle_id,
                Recommendation.user_id == user_id,
            )
            .order_by(Recommendation.created_at.desc())
            .limit(limit)
        )
        return list(db.session.execute(stmt).scalars())

    @staticmethod
    def recent_for_user(user_id: int, limit: int = 5) -> list[Recommendation]:
        stmt = (
            db.select(Recommendation)
            .where(Recommendation.user_id == user_id)
            .order_by(Recommendation.created_at.desc())
            .limit(limit)
        )
        return list(db.session.execute(stmt).scalars())

    @staticmethod
    def add_action(recommendation_id: int, data: dict[str, Any]) -> FarmerAction:
        action = FarmerAction(recommendation_id=recommendation_id, **data)
        db.session.add(action)
        db.session.commit()
        return action


class FeedbackRepository:
    """recommendation_feedback data access (owner-scoped)."""

    @staticmethod
    def create(user_id: int, recommendation_id: int, data: dict[str, Any]) -> RecommendationFeedback:
        feedback = RecommendationFeedback(
            user_id=user_id, recommendation_id=recommendation_id, **data
        )
        db.session.add(feedback)
        db.session.commit()
        return feedback

    @staticmethod
    def get_owned(feedback_id: int, user_id: int) -> Optional[RecommendationFeedback]:
        feedback = db.session.get(RecommendationFeedback, feedback_id)
        if feedback is None or feedback.user_id != user_id:
            return None
        return feedback


class ConversationRepository:
    """conversations + messages for the versioned copilot API."""

    @staticmethod
    def create(user_id: int, mode: str) -> Conversation:
        conversation = Conversation(user_id=user_id, mode=mode)
        db.session.add(conversation)
        db.session.commit()
        return conversation

    @staticmethod
    def get_owned(conversation_id: str | int, user_id: int) -> Optional[Conversation]:
        """Look up by UUID string or integer id; never match another user's."""
        stmt = db.select(Conversation).where(
            Conversation.user_id == user_id,
            db.or_(
                Conversation.uuid == str(conversation_id),
                Conversation.id == conversation_id if isinstance(conversation_id, int) else Conversation.id < 0,
            ),
        )
        return db.session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def add_message(conversation_id: int, role: str, content: str,
                    sources: dict[str, Any] | None = None) -> Message:
        message = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            sources_json=json.dumps(sources, ensure_ascii=False) if sources else None,
        )
        db.session.add(message)
        db.session.commit()
        return message

    @staticmethod
    def get_message(message_id: int) -> Optional[Message]:
        return db.session.get(Message, message_id)

    @staticmethod
    def recent_messages(conversation_id: int, limit: int = 6) -> list[Message]:
        stmt = (
            db.select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return list(reversed(db.session.execute(stmt).scalars().all()))


class AssistantRunRepository:
    """assistant_runs provenance writes."""

    @staticmethod
    def start(conversation_id: int, provider: str, model: str | None,
              prompt_template_version: str) -> AssistantRun:
        run = AssistantRun(
            conversation_id=conversation_id,
            provider=provider,
            model=model,
            prompt_template_version=prompt_template_version,
        )
        db.session.add(run)
        db.session.commit()
        return run

    @staticmethod
    def complete(run_id: int, *, message_id: int | None, context_record_ids: list[int],
                 retrieved_source_ids: list[int], status: str,
                 error_category: str | None = None) -> AssistantRun:
        from ..core.time import utc_now

        run = db.session.get(AssistantRun, run_id)
        if run is None:
            return None  # type: ignore[return-value]
        run.message_id = message_id
        run.context_record_ids = json.dumps(context_record_ids)
        run.retrieved_source_ids = json.dumps(retrieved_source_ids)
        run.completed_at = utc_now()
        run.status = status
        run.error_category = error_category
        db.session.commit()
        return run


__all__ = [
    "KnowledgeRepository",
    "RecommendationRepository",
    "FeedbackRepository",
    "ConversationRepository",
    "AssistantRunRepository",
]
