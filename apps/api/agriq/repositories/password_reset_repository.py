"""Password-reset token repository (Phase 7.1).

Tokens are stored as SHA-256 digests only. A token is consumed exactly once by
setting ``used_at``; consumption is a compare-and-set so two concurrent requests
holding the same token cannot both succeed.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from ..core.time import utc_now
from ..core.tokens import generate_token, hash_address, hash_token
from ..extensions import db
from ..models.password_reset import PasswordResetToken


class PasswordResetRepository:
    """Data-access wrapper around the password_reset_tokens table."""

    @staticmethod
    def issue(
        user_id: int, *, ttl_minutes: int, address: str | None = None, salt: str = ""
    ) -> tuple[PasswordResetToken, str]:
        """Invalidate outstanding tokens and issue a fresh single-use one."""
        PasswordResetRepository.invalidate_outstanding(user_id)
        raw_token = generate_token()
        now = utc_now()
        row = PasswordResetToken(
            user_id=user_id,
            token_hash=hash_token(raw_token),
            created_at=now,
            expires_at=now + timedelta(minutes=max(1, ttl_minutes)),
            requested_ip_hash=hash_address(address, salt=salt),
        )
        db.session.add(row)
        db.session.commit()
        return row, raw_token

    @staticmethod
    def get_by_token(raw_token: str | None) -> Optional[PasswordResetToken]:
        if not raw_token:
            return None
        return db.session.execute(
            db.select(PasswordResetToken).where(
                PasswordResetToken.token_hash == hash_token(raw_token)
            )
        ).scalar_one_or_none()

    @staticmethod
    def consume(row: PasswordResetToken) -> bool:
        """Mark a usable token consumed. False when it was already used/expired."""
        if not row.is_usable():
            return False
        row.used_at = utc_now()
        db.session.commit()
        return True

    @staticmethod
    def invalidate_outstanding(user_id: int) -> int:
        """Expire every unused token of a user (a new request supersedes them)."""
        rows = db.session.execute(
            db.select(PasswordResetToken).where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
            )
        ).scalars().all()
        now = utc_now()
        for row in rows:
            row.used_at = now
        if rows:
            db.session.commit()
        return len(rows)


__all__ = ["PasswordResetRepository"]
