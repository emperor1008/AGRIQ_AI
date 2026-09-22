"""User repository: all user-table reads/writes (no request handling)."""
from __future__ import annotations

from typing import Optional

from ..core.time import utc_now
from ..extensions import db
from ..models.user import User


class UserRepository:
    """Data-access wrapper around the users table."""

    @staticmethod
    def get_by_contact(contact: str) -> Optional[User]:
        return db.session.execute(
            db.select(User).where(User.contact == contact)
        ).scalar_one_or_none()

    @staticmethod
    def get_by_id(user_id: int) -> Optional[User]:
        return db.session.get(User, user_id)

    @staticmethod
    def create(contact: str, password: str) -> User:
        user = User(contact=contact)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    @staticmethod
    def count() -> int:
        return int(db.session.scalar(db.select(db.func.count(User.id))) or 0)

    @staticmethod
    def touch_last_login(user: User) -> None:
        """Record a successful sign-in (UTC)."""
        user.last_login_at = utc_now()
        db.session.commit()

    @staticmethod
    def set_active(user: User, active: bool) -> None:
        user.is_active = active
        db.session.commit()


__all__ = ["UserRepository"]
