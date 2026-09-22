"""User database model (users table)."""
from __future__ import annotations

from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db


class User(db.Model):
    """Registered user account.

    OTP/email verification is a pre-launch security gate (see
    docs/SECURITY_AND_ACCESS.md), so ownership of a contact is not claimed.
    """

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    contact = db.Column(db.String(200), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_login_at = db.Column(db.DateTime(timezone=True), nullable=True)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        try:
            return check_password_hash(self.password_hash or "", password)
        except ValueError:
            return False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "contact": self.contact,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login_at": self.last_login_at.isoformat() if self.last_login_at else None,
        }


__all__ = ["User"]
