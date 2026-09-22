"""Singleton Flask extension instances for AGRIQ AI.

Extensions are instantiated here without an application and bound to the
app inside :func:`agriq.app_factory.create_app` (or the package-level
``create_app``). This avoids circular imports between blueprints and the
factory.
"""
from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy

db: SQLAlchemy = SQLAlchemy()

limiter: Limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)

__all__ = ["db", "limiter"]
