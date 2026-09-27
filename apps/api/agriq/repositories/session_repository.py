"""Session repository: server-side session records (Phase 7.1).

All reads/writes of the ``user_sessions`` table live here. The raw session token
never reaches the database — only its SHA-256 digest — and lookup is a single
indexed query that also fetches the owning user, so verifying a request costs one
statement rather than a session query plus a user query.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from ..core.time import utc_now
from ..core.tokens import generate_token, hash_address, hash_token
from ..extensions import db
from ..models.user import User
from ..models.user_session import UserSession

#: ``last_seen_at`` is only written when it is older than this (avoids a write
#: on every single request while still keeping the sliding window honest).
_TOUCH_INTERVAL_SECONDS = 60


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SessionRepository:
    """Data-access wrapper around the user_sessions table."""

    @staticmethod
    def create(
        user: User,
        *,
        idle_timeout_hours: int,
        absolute_timeout_hours: int,
        user_agent: str | None = None,
        address: str | None = None,
        salt: str = "",
    ) -> tuple[UserSession, str]:
        """Create a session row and return ``(row, raw_token)``."""
        raw_token = generate_token()
        now = utc_now()
        row = UserSession(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=idle_timeout_hours),
            absolute_expires_at=now + timedelta(hours=absolute_timeout_hours),
            user_agent=(str(user_agent)[:160] if user_agent else None),
            ip_hash=hash_address(address, salt=salt),
        )
        db.session.add(row)
        db.session.commit()
        return row, raw_token

    @staticmethod
    def resolve(raw_token: str | None) -> tuple[User, UserSession] | None:
        """Return ``(user, session)`` for a live token, else ``None``.

        Revoked, expired and unknown tokens all return ``None`` — one shape of
        failure, so a caller cannot distinguish them.
        """
        if not raw_token:
            return None
        row = db.session.execute(
            db.select(UserSession).where(UserSession.token_hash == hash_token(raw_token))
        ).scalar_one_or_none()
        if row is None or not row.is_live():
            return None
        user = db.session.get(User, row.user_id)
        if user is None:
            return None
        return user, row

    @staticmethod
    def touch(row: UserSession, *, idle_timeout_hours: int) -> None:
        """Refresh the sliding window at most once per minute."""
        now = utc_now()
        if (_aware(now) - _aware(row.last_seen_at)).total_seconds() < _TOUCH_INTERVAL_SECONDS:
            return
        row.last_seen_at = now
        proposed = now + timedelta(hours=idle_timeout_hours)
        cap = _aware(row.absolute_expires_at)
        if _aware(row.expires_at) < cap:
            row.expires_at = min(proposed, cap)
        db.session.commit()

    @staticmethod
    def get_by_id(session_id: int, user_id: int) -> Optional[UserSession]:
        """Fetch one session row, scoped to its owner (never cross-user)."""
        return db.session.execute(
            db.select(UserSession).where(
                UserSession.id == session_id, UserSession.user_id == user_id
            )
        ).scalar_one_or_none()

    @staticmethod
    def revoke(row: UserSession, reason: str) -> None:
        if row.revoked_at is None:
            row.revoked_at = utc_now()
            row.revoked_reason = reason[:40]
            db.session.commit()

    @staticmethod
    def revoke_by_token(raw_token: str | None, reason: str) -> bool:
        """Revoke the session identified by a raw token. True when one was found."""
        if not raw_token:
            return False
        row = db.session.execute(
            db.select(UserSession).where(UserSession.token_hash == hash_token(raw_token))
        ).scalar_one_or_none()
        if row is None:
            return False
        SessionRepository.revoke(row, reason)
        return True

    @staticmethod
    def revoke_all_for_user(user_id: int, reason: str) -> int:
        """Revoke every live session of a user; returns how many were revoked."""
        rows = db.session.execute(
            db.select(UserSession).where(
                UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
            )
        ).scalars().all()
        now = utc_now()
        for row in rows:
            row.revoked_at = now
            row.revoked_reason = reason[:40]
        if rows:
            db.session.commit()
        return len(rows)

    @staticmethod
    def list_for_user(user_id: int, *, limit: int = 20) -> Sequence[UserSession]:
        """Newest-first sessions of one user (live and recently revoked)."""
        return db.session.execute(
            db.select(UserSession)
            .where(UserSession.user_id == user_id)
            .order_by(UserSession.created_at.desc())
            .limit(limit)
        ).scalars().all()

    @staticmethod
    def purge_dead(before: datetime | None = None) -> int:
        """Delete long-dead rows (housekeeping; never touches live sessions)."""
        moment = before or (utc_now() - timedelta(days=30))
        resource = db.session.execute(
            db.delete(UserSession).where(
                db.or_(
                    UserSession.revoked_at.is_not(None),
                    UserSession.absolute_expires_at < moment,
                )
            )
        )
        db.session.commit()
        return int(resource.rowcount or 0)


__all__ = ["SessionRepository"]
