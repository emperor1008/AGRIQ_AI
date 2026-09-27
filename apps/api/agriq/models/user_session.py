"""Server-side session records (Phase 7.1).

A signed cookie is not by itself proof of identity: it cannot be revoked,
expired server-side, or invalidated when a password changes. Each successful
sign-in therefore creates one row here, and every authenticated request must
find a live row for the cookie's opaque token.

Only the SHA-256 hash of the token is stored, so a database leak does not yield
usable credentials. No device fingerprinting is collected: the user-agent string
is stored truncated for display in the session list, and the client address is
stored only as a salted hash for abuse triage.
"""
from __future__ import annotations

from datetime import datetime

from ..core.time import utc_now
from ..extensions import db


class UserSession(db.Model):
    """One signed-in browser/device session."""

    __tablename__ = "user_sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    #: SHA-256 hex digest of the opaque session token (never the token itself).
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    #: Last request seen; refreshed on activity (sliding window).
    last_seen_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    #: Sliding expiry — extended by activity.
    expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    #: Hard cap — never extended, whatever the activity.
    absolute_expires_at = db.Column(db.DateTime(timezone=True), nullable=False)
    revoked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    #: Why the row was revoked (logout / password_reset / user_revoked).
    revoked_reason = db.Column(db.String(40), nullable=True)
    #: Truncated user agent, for "your active sessions" display only.
    user_agent = db.Column(db.String(160), nullable=True)
    #: Salted hash of the client address; never the raw address.
    ip_hash = db.Column(db.String(64), nullable=True)

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None

    def is_live(self, now: datetime | None = None) -> bool:
        """True only for a non-revoked session inside both expiry windows."""
        moment = now or utc_now()
        if self.revoked_at is not None:
            return False
        for value in (self.expires_at, self.absolute_expires_at):
            if value is None:
                return False
            if _aware(value) <= moment:
                return False
        return True

    def to_dict(self, *, current: bool = False) -> dict:
        return {
            "id": self.id,
            "created_at": _iso(self.created_at),
            "last_seen_at": _iso(self.last_seen_at),
            "expires_at": _iso(self.expires_at),
            "revoked_at": _iso(self.revoked_at),
            "revoked_reason": self.revoked_reason,
            "user_agent": self.user_agent,
            "current": current,
        }


def _aware(value: datetime) -> datetime:
    """Normalise a stored timestamp to aware UTC (SQLite returns naive)."""
    if value.tzinfo is None:
        from datetime import timezone

        return value.replace(tzinfo=timezone.utc)
    return value


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value else None


__all__ = ["UserSession"]
