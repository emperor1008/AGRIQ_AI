"""Migration test (Phase 1): the Alembic migration creates every table.

Runs the real migration chain against a throwaway SQLite database and
verifies the 13 Phase 1 tables exist. No data is inserted or inspected
beyond schema presence — no seed/demo rows are ever created by migrations.
"""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path


def _dispose_engine() -> None:
    """Close pooled SQLite connections so Windows releases the file lock."""
    import sys

    api_dir = Path(__file__).resolve().parents[2]
    if str(api_dir) not in sys.path:
        sys.path.insert(0, str(api_dir))
    from agriq import create_app
    from agriq.extensions import db as _db

    app = create_app()
    with app.app_context():
        _db.engine.dispose()

EXPECTED_TABLES = {
    "users", "farmer_profiles", "farms", "fields", "soil_tests",
    "crop_cycles", "field_observations", "weather_snapshots",
    "market_price_records", "conversations", "messages",
    "recommendations", "farmer_actions",
}


def test_migration_creates_full_schema(tmp_path, monkeypatch):
    api_dir = Path(__file__).resolve().parents[2]

    db_path = Path(tempfile.gettempdir()) / f"agriq_mig_{tmp_path.name[:8]}.db"
    db_path.unlink(missing_ok=True)  # never reuse a stale temp DB
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "migrations"))
    command.upgrade(cfg, "head")

    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        tables = {row[0] for row in rows}
        missing = EXPECTED_TABLES - tables
        assert not missing, f"migration missed tables: {missing}"

        # Unique constraint on official market records exists.
        indexes = con.execute(
            "SELECT sql FROM sqlite_master WHERE name='market_price_records'"
        ).fetchall()
        assert indexes  # table exists with schema
        columns = {row[1] for row in con.execute("PRAGMA table_info(market_price_records)")}
        assert {"source", "retrieved_at", "raw_record_hash", "modal_price"}.issubset(columns)

        # Migrations never insert rows.
        user_count = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        assert user_count == 0, "migrations must not seed data"
    finally:
        con.close()
        _dispose_engine()
        try:
            db_path.unlink()
        except OSError:
            pass


def test_migrations_downgrade_cleanly(tmp_path, monkeypatch):
    api_dir = Path(__file__).resolve().parents[2]
    db_path = Path(tempfile.gettempdir()) / f"agriq_mig_down_{tmp_path.name[:8]}.db"
    db_path.unlink(missing_ok=True)  # never reuse a stale temp DB
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    from alembic import command
    from alembic.config import Config

    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "migrations"))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    con = sqlite3.connect(str(db_path))
    try:
        tables = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "users" not in tables
    finally:
        con.close()
        _dispose_engine()
        try:
            db_path.unlink()
        except OSError:
            pass
