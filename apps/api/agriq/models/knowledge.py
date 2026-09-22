"""Phase 2 models: verified knowledge base, recommendation feedback and
assistant run provenance.

Rules:
- Knowledge sources carry a review workflow; only ``approved`` sources may
  ground farmer recommendations (enforced in the retriever, not the UI).
- Chunks keep their section reference and content hash — no fake embeddings
  are stored; ``embedding_reference`` stays NULL until a real provider exists.
- Feedback rows belong to exactly one user and never overwrite the original
  recommendation or its evidence.
- Assistant runs record which context records and sources were used, never
  API keys or full provider payloads.
"""
from __future__ import annotations

from datetime import datetime

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.utcnow()


class KnowledgeSource(db.Model):
    """A versioned, reviewable external agricultural knowledge source."""

    __tablename__ = "knowledge_sources"

    STATUS_PENDING = "pending_review"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_ARCHIVED = "archived"
    STATUSES = {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED, STATUS_ARCHIVED}

    id = db.Column(db.Integer, primary_key=True)
    source_key = db.Column(db.String(120), nullable=False, unique=True, index=True)
    title = db.Column(db.String(300), nullable=False)
    organisation = db.Column(db.String(200), nullable=False)
    source_url = db.Column(db.String(500), nullable=False)
    document_type = db.Column(db.String(60), nullable=False, default="advisory")
    crop = db.Column(db.String(120), nullable=True)
    region = db.Column(db.String(120), nullable=True)
    language = db.Column(db.String(20), nullable=False, default="en")
    publication_date = db.Column(db.Date, nullable=True)
    licence_note = db.Column(db.String(300), nullable=True)
    checksum = db.Column(db.String(64), nullable=True)
    version = db.Column(db.String(20), nullable=False, default="1")
    review_status = db.Column(db.String(30), nullable=False, default=STATUS_PENDING, index=True)
    retrieved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    chunks = db.relationship("KnowledgeChunk", back_populates="source", lazy="dynamic",
                             cascade="all, delete-orphan")


class KnowledgeChunk(db.Model):
    """A meaningfully-sectioned passage of one approved (or pending) source."""

    __tablename__ = "knowledge_chunks"

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey("knowledge_sources.id"), nullable=False, index=True)
    section_reference = db.Column(db.String(200), nullable=True)
    content = db.Column(db.Text, nullable=False)
    content_hash = db.Column(db.String(64), nullable=False, index=True)
    embedding_reference = db.Column(db.String(200), nullable=True)  # NULL: no embedding provider yet
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    source = db.relationship("KnowledgeSource", back_populates="chunks")


class RecommendationFeedback(db.Model):
    """Farmer feedback on a recommendation (evaluation loop, Phase 2 §15)."""

    __tablename__ = "recommendation_feedback"

    STATUS_PLANNED = "planned"
    STATUS_COMPLETED = "completed"
    STATUS_SKIPPED = "skipped"
    STATUS_NEEDS_HELP = "needs_help"
    STATUSES = {STATUS_PLANNED, STATUS_COMPLETED, STATUS_SKIPPED, STATUS_NEEDS_HELP}

    id = db.Column(db.Integer, primary_key=True)
    recommendation_id = db.Column(db.Integer, db.ForeignKey("recommendations.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False)
    helpfulness = db.Column(db.Integer, nullable=True)  # 1-5, optional
    farmer_note = db.Column(db.Text, nullable=True)
    outcome = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    recommendation = db.relationship("Recommendation")
    user = db.relationship("User")


class AssistantRun(db.Model):
    """One copilot execution with full provenance (no secrets, no payloads)."""

    __tablename__ = "assistant_runs"

    STATUS_OK = "completed"
    STATUS_FAILED = "failed"
    STATUS_UNAVAILABLE = "unavailable"

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=False, index=True)
    message_id = db.Column(db.Integer, db.ForeignKey("messages.id"), nullable=True)
    provider = db.Column(db.String(60), nullable=False)
    model = db.Column(db.String(80), nullable=True)
    prompt_template_version = db.Column(db.String(20), nullable=False, default="copilot-prompt-v1")
    context_record_ids = db.Column(db.Text, nullable=True)   # JSON: ids actually shared with the model
    retrieved_source_ids = db.Column(db.Text, nullable=True) # JSON: knowledge source ids used
    started_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.String(20), nullable=False, default=STATUS_OK)
    error_category = db.Column(db.String(60), nullable=True)

    conversation = db.relationship("Conversation")


__all__ = ["KnowledgeSource", "KnowledgeChunk", "RecommendationFeedback", "AssistantRun"]
