"""Voice repositories (Phase 3): owner-scoped data access for consent,
sessions, transcripts and synthesised audio.

Every read of a farmer-owned voice resource goes through a ``get_owned``-
style method scoped to the session user id; another user's resource is
indistinguishable from a missing one (404 at the API layer).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from ..extensions import db
from ..models.voice import SynthesisedAudio, Transcript, VoiceConsent, VoiceSession


class VoiceConsentRepository:
    @staticmethod
    def active_for_user(user_id: int) -> Optional[VoiceConsent]:
        stmt = (
            db.select(VoiceConsent)
            .where(VoiceConsent.user_id == user_id, VoiceConsent.revoked_at.is_(None))
            .order_by(VoiceConsent.consented_at.desc())
            .limit(1)
        )
        return db.session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def create(user_id: int, data: dict[str, Any]) -> VoiceConsent:
        consent = VoiceConsent(user_id=user_id, **data)
        db.session.add(consent)
        db.session.commit()
        return consent

    @staticmethod
    def revoke(consent: VoiceConsent) -> VoiceConsent:
        from ..core.time import utc_now

        consent.revoked_at = utc_now()
        db.session.commit()
        return consent


class VoiceSessionRepository:
    @staticmethod
    def create(user_id: int, data: dict[str, Any]) -> VoiceSession:
        session = VoiceSession(user_id=user_id, **data)
        db.session.add(session)
        db.session.commit()
        return session

    @staticmethod
    def get_owned(session_ref: str | int, user_id: int) -> Optional[VoiceSession]:
        """Lookup by uuid (string) or integer id; never matches another user."""
        filters = [VoiceSession.user_id == user_id]
        if isinstance(session_ref, int):
            filters.append(VoiceSession.id == session_ref)
        else:
            filters.append(VoiceSession.uuid == str(session_ref))
        return db.session.execute(
            db.select(VoiceSession).where(*filters)
        ).scalar_one_or_none()

    @staticmethod
    def update(session: VoiceSession, data: dict[str, Any]) -> VoiceSession:
        for key, value in data.items():
            setattr(session, key, value)
        db.session.commit()
        return session

    @staticmethod
    def mark_expired_sessions(now: datetime) -> int:
        """Flip past-expiry sessions to expired (audio cleanup sweep)."""
        stmt = db.select(VoiceSession).where(
            VoiceSession.expires_at.is_not(None),
            VoiceSession.expires_at < now,
            VoiceSession.status.notin_(
                (VoiceSession.STATUS_DELETED, VoiceSession.STATUS_EXPIRED)
            ),
        )
        sessions = list(db.session.execute(stmt).scalars())
        for session in sessions:
            session.status = VoiceSession.STATUS_EXPIRED
            session.audio_storage_key = None   # audio deleted with the row state
        if sessions:
            db.session.commit()
        return len(sessions)


class TranscriptRepository:
    @staticmethod
    def create_for_session(session_id: int, data: dict[str, Any]) -> Transcript:
        transcript = Transcript(voice_session_id=session_id, **data)
        db.session.add(transcript)
        db.session.commit()
        return transcript

    @staticmethod
    def latest_for_session(session_id: int) -> Optional[Transcript]:
        stmt = (
            db.select(Transcript)
            .where(Transcript.voice_session_id == session_id)
            .order_by(Transcript.created_at.desc())
            .limit(1)
        )
        return db.session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def get_owned(transcript_id: int, user_id: int) -> Optional[Transcript]:
        return db.session.execute(
            db.select(Transcript)
            .join(VoiceSession, Transcript.voice_session_id == VoiceSession.id)
            .where(Transcript.id == transcript_id, VoiceSession.user_id == user_id)
        ).scalar_one_or_none()


class SynthesisedAudioRepository:
    @staticmethod
    def create(user_id: int, data: dict[str, Any]) -> SynthesisedAudio:
        audio = SynthesisedAudio(user_id=user_id, **data)
        db.session.add(audio)
        db.session.commit()
        return audio

    @staticmethod
    def get_owned(audio_ref: str | int, user_id: int) -> Optional[SynthesisedAudio]:
        filters = [SynthesisedAudio.user_id == user_id]
        if isinstance(audio_ref, int):
            filters.append(SynthesisedAudio.id == audio_ref)
        else:
            filters.append(SynthesisedAudio.uuid == str(audio_ref))
        return db.session.execute(
            db.select(SynthesisedAudio).where(*filters)
        ).scalar_one_or_none()

    @staticmethod
    def mark_deleted(audio: SynthesisedAudio) -> SynthesisedAudio:
        from ..core.time import utc_now

        audio.deleted_at = utc_now()
        audio.storage_key = None
        db.session.commit()
        return audio

    @staticmethod
    def active_for_message(message_id: int, user_id: int) -> Optional[SynthesisedAudio]:
        stmt = db.select(SynthesisedAudio).where(
            SynthesisedAudio.message_id == message_id,
            SynthesisedAudio.user_id == user_id,
            SynthesisedAudio.deleted_at.is_(None),
        )
        return db.session.execute(stmt).scalar_one_or_none()


__all__ = [
    "VoiceConsentRepository",
    "VoiceSessionRepository",
    "TranscriptRepository",
    "SynthesisedAudioRepository",
]
