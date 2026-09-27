"""Phase 7.1 auth hardening: server-side sessions + password-reset tokens.

Revision ID: 0007_auth_sessions
Revises: 0006_risk_provenance
Create Date: 2026-09-26

Two additive tables, no changes to existing tables and no seed rows:

1. ``user_sessions`` — one row per signed-in session. The cookie carries an
   opaque token; only its SHA-256 digest is stored here, so a database leak does
   not yield usable credentials. This is what makes logout, expiry, password
   change and explicit revocation effective server-side.

2. ``password_reset_tokens`` — single-use, expiring, hashed reset tokens.

Sessions created before this revision (cookie-only, no row) are intentionally
*not* adopted: they cannot be revoked, so they stop being accepted and the user
signs in again. No session is fabricated to keep anyone signed in.
"""
from __future__ import annotations

from alembic import op

revision = "0007_auth_sessions"
down_revision = "0006_risk_provenance"
branch_labels = None
depends_on = None

_AUTH_TABLES = ("user_sessions", "password_reset_tokens")


def upgrade() -> None:
    """Create the Phase 7.1 auth tables from model metadata (idempotent)."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401  (register all models on the metadata)

    bind = op.get_bind()
    existing = set(db.inspect(bind).get_table_names())
    for table in _AUTH_TABLES:
        if table in existing:
            continue
        db.metadata.tables[table].create(bind=bind)


def downgrade() -> None:
    """Drop the Phase 7.1 auth tables (sessions are rebuildable by signing in)."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401

    bind = op.get_bind()
    for table in reversed(_AUTH_TABLES):
        if table in db.metadata.tables:
            db.metadata.tables[table].drop(bind=bind, checkfirst=True)


__all__ = ["revision", "down_revision", "upgrade", "downgrade"]
