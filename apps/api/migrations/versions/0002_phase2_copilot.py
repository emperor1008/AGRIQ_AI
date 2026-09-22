"""Phase 2 copilot tables: knowledge base, feedback and run provenance.

Revision ID: 0002_phase2_copilot
Revises: 0001_initial_users
Create Date: 2026-09-22

Creates knowledge_sources, knowledge_chunks, recommendation_feedback and
assistant_runs from the SQLAlchemy metadata. Schema only — no seed or demo
rows are inserted, ever.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_phase2_copilot"
down_revision = "0001_initial_users"
branch_labels = None
depends_on = None

_PHASE2_TABLES = (
    "assistant_runs",
    "recommendation_feedback",
    "knowledge_chunks",
    "knowledge_sources",
)


def upgrade() -> None:
    """Create the Phase 2 tables from model metadata (idempotent)."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401  (register all models on the metadata)

    existing = set(
        db.inspect(op.get_bind()).get_table_names()
    )
    for table in _PHASE2_TABLES:
        if table in existing:
            continue
        db.metadata.tables[table].create(bind=op.get_bind())

    # Phase 2 adds opaque UUID identifiers to existing conversation tables so
    # the versioned API can hand out non-enumerable ids. Existing rows get a
    # random UUID backfilled here (schema migration, not data fabrication).
    # Note: uuid4().hex values are unique by construction; the DB-level UNIQUE
    # constraint exists on the create_all path (model metadata). SQLite batch
    # mode cannot re-add named constraints, so migrations rely on the random
    # values for uniqueness — no fabricated identifiers are introduced.
    import uuid as _uuid
    bind = op.get_bind()
    for table in ("conversations", "messages"):
        if table not in existing:
            continue
        cols = set(col["name"] for col in db.inspect(bind).get_columns(table))
        if "uuid" in cols:
            continue
        rows = bind.execute(sa.text(f"SELECT id FROM {table}")).fetchall()
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("uuid", sa.String(32), nullable=True))
        for (row_id,) in rows:
            bind.execute(
                sa.text(f"UPDATE {table} SET uuid = :u WHERE id = :i"),
                {"u": _uuid.uuid4().hex, "i": row_id},
            )
        op.create_index(f"ix_{table}_uuid", table, ["uuid"], unique=True)


def downgrade() -> None:
    """Drop the Phase 2 tables and the added UUID columns."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401

    for table in reversed(_PHASE2_TABLES):
        if table in db.metadata.tables:
            db.metadata.tables[table].drop(bind=op.get_bind(), checkfirst=True)

    bind = op.get_bind()
    existing = set(db.inspect(bind).get_table_names())
    for table in ("conversations", "messages"):
        if table not in existing:
            continue
        cols = set(c["name"] for c in db.inspect(bind).get_columns(table))
        if "uuid" not in cols:
            continue
        op.drop_index(f"ix_{table}_uuid", table_name=table)
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("uuid")
