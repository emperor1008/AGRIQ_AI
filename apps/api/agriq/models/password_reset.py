"""Single-use, expiring password-reset tokens (Phase 7.1).

Only the SHA-256 hash of a reset token is stored. A token is consumed exactly
once (``used_at``), expires after a short window, and every reset revokes the
account's live sessions. No token is ever logged, and no reset is ever reported
as "email sent" unless a real provider accepted the message.
"""
from __future__ import annotations

from datetime import datetime

from ..core.time import utc_now
from ..extensions import db


class PasswordResetToken(db.Model):
    """One outstanding (or consumed) password-reset request."""

    __tablename__ = "password_reset_tokens"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    #: SHA-256 hex digest of the raw token handed to the user.
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    #: Set the moment the token is consumed; a second attempt is refused.
    used_at = db.Column(db.DateTime(timezone=True), nullable=True)
    #: Salted hash of the requesting address (abuse triage only).
    requested_ip_hash = db.Column(db.String(64), nullable=True)

    def is_usable(self, now: datetime | None = None) -> bool:
        moment = now or utc_now()
        if self.used_at is not None:
            return False
        expires = self.expires_at
        if expires is None:
            return False
        if expires.tzinfo is None:
            from datetime import timezone

            expires = expires.replace(tzinfo=timezone.utc)
        return expires > moment


__all__ = ["PasswordResetToken"]
