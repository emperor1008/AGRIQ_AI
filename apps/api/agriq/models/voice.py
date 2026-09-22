"""Phase 3 models: voice consent, voice sessions, transcripts and synthesised
audio.

Rules enforced at the model level:
- ``voice_consents`` records the consent version actually shown; revocation
  is stored, never destructive (auditability).
- ``voice_sessions`` never stores provider credentials or raw payloads; the
  audio storage key is a random server-side identifier, never a client name.
- ``transcripts`` keeps raw and corrected transcripts separately so a
  correction is always distinguishable from what ASR produced.
- ``synthesised_audio`` rows expire and are deleted; no public URLs exist.
"""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from ..extensions import db


def _utcnow() -> datetime:
    return datetime.utcnow()


class VoiceConsent(db.Model):
    """A farmer's informed consent record for voice processing."""

    __tablename__ = "voice_consents"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(32), unique=True, index=True, default=lambda: uuid4().hex)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    consent_version = db.Column(db.String(20), nullable=False)
    speech_provider_processing_allowed = db.Column(db.Boolean, nullable=False, default=False)
    evaluation_use_allowed = db.Column(db.Boolean, nullable=False, default=False)
    audio_retention_allowed = db.Column(db.Boolean, nullable=False, default=False)
    consented_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user = db.relationship("User")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class VoiceSession(db.Model):
    """One voice interaction from recording to copilot answer."""

    __tablename__ = "voice_sessions"

    STATUS_CREATED = "created"
    STATUS_UPLOADED = "uploaded"
    STATUS_QUEUED = "queued"              # offline queue marker (client-side label)
    STATUS_PROCESSING = "processing"
    STATUS_TRANSCRIPT_READY = "transcript_ready"
    STATUS_TRANSCRIPT_CONFIRMED = "transcript_confirmed"
    STATUS_COPILOT_COMPLETED = "copilot_completed"
    STATUS_FAILED = "failed"
    STATUS_EXPIRED = "expired"
    STATUS_DELETED = "deleted"
    STATUSES = {
        STATUS_CREATED, STATUS_UPLOADED, STATUS_QUEUED, STATUS_PROCESSING,
        STATUS_TRANSCRIPT_READY, STATUS_TRANSCRIPT_CONFIRMED,
        STATUS_COPILOT_COMPLETED, STATUS_FAILED, STATUS_EXPIRED, STATUS_DELETED,
    }

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(32), unique=True, index=True, default=lambda: uuid4().hex)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversations.id"), nullable=True)
    field_id = db.Column(db.Integer, db.ForeignKey("fields.id"), nullable=True)
    crop_cycle_id = db.Column(db.Integer, db.ForeignKey("crop_cycles.id"), nullable=True)
    language_requested = db.Column(db.String(20), nullable=False)
    language_detected = db.Column(db.String(20), nullable=True)
    provider = db.Column(db.String(60), nullable=True)
    provider_model = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(30), nullable=False, default=STATUS_CREATED, index=True)
    audio_storage_key = db.Column(db.String(200), nullable=True)   # private, random
    audio_retained = db.Column(db.Boolean, nullable=False, default=False)
    actual_duration_seconds = db.Column(db.Float, nullable=True)   # measured, never estimated
    audio_format = db.Column(db.String(40), nullable=True)
    failure_reason = db.Column(db.String(200), nullable=True)
    started_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user = db.relationship("User")
    conversation = db.relationship("Conversation")
    transcripts = db.relationship("Transcript", back_populates="voice_session",
                                  lazy="dynamic", cascade="all, delete-orphan")


class Transcript(db.Model):
    """ASR output for one voice session (raw + farmer-corrected kept apart)."""

    __tablename__ = "transcripts"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(32), unique=True, index=True, default=lambda: uuid4().hex)
    voice_session_id = db.Column(db.Integer, db.ForeignKey("voice_sessions.id"), nullable=False, index=True)
    raw_transcript = db.Column(db.Text, nullable=True)             # exactly what the provider returned
    corrected_transcript = db.Column(db.Text, nullable=True)       # farmer-confirmed version
    confidence_available = db.Column(db.Boolean, nullable=False, default=False)
    provider_confidence = db.Column(db.Float, nullable=True)       # NULL when provider gives none
    confidence_source = db.Column(db.String(40), nullable=True)
    language_detected = db.Column(db.String(20), nullable=True)
    correction_confirmed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    voice_session = db.relationship("VoiceSession", back_populates="transcripts")


class SynthesisedAudio(db.Model):
    """One TTS audio artefact for a copilot answer message."""

    __tablename__ = "synthesised_audio"

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(32), unique=True, index=True, default=lambda: uuid4().hex)
    message_id = db.Column(db.Integer, db.ForeignKey("messages.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    language = db.Column(db.String(20), nullable=False)
    provider = db.Column(db.String(60), nullable=False)
    provider_model = db.Column(db.String(120), nullable=True)
    storage_key = db.Column(db.String(200), nullable=False)        # private, random
    format = db.Column(db.String(40), nullable=False, default="audio/mpeg")
    actual_duration_seconds = db.Column(db.Float, nullable=True)   # measured from decoded audio
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    message = db.relationship("Message")
    user = db.relationship("User")

    @property
    def is_available(self) -> bool:
        return self.deleted_at is None


__all__ = ["VoiceConsent", "VoiceSession", "Transcript", "SynthesisedAudio"]
