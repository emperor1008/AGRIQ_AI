"""Alembic environment for AGRIQ AI migrations.

Runs inside the Flask app context so ``db.metadata`` and the configured
DATABASE_URL are used. Migrations create schema only — no seed or demo
data is ever inserted.
"""
from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from flask import current_app

# Make the api package importable when alembic runs standalone.
API_DIR = Path(__file__).resolve().parents[1]
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

from agriq import create_app  # noqa: E402
from agriq.extensions import db  # noqa: E402

config = context.config

if config.config_file_name is not None and (API_DIR / "alembic.ini").exists():
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = db.metadata


def _flask_app():
    """Create a fresh app so the env-configured DATABASE_URL is honoured.

    A cached/current app is deliberately NOT reused: migrations must run
    against the database named by the environment, not whatever app context
    happens to be active in the calling process.
    """
    return create_app()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection."""
    app = _flask_app()
    with app.app_context():
        url = app.config.get("SQLALCHEMY_DATABASE_URI")
        context.configure(
            url=url,
            target_metadata=target_metadata,
            literal_binds=True,
            dialect_opts={"paramstyle": "named"},
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live connection."""
    app = _flask_app()
    with app.app_context():
        engine = db.engine
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,  # SQLite-friendly ALTER support
            )
            with context.begin_transaction():
                context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
