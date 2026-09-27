"""Phase 7.2: Farming Techniques / agricultural knowledge base.

Revision ID: 0008_farming_knowledge
Revises: 0007_auth_sessions
Create Date: 2026-09-26

Additive and idempotent — no existing table is rewritten, no row is deleted and
no seed data is inserted:

1. Four nullable provenance columns on the existing ``knowledge_sources`` table
   (``source_type``, ``accessed_at``, ``last_verified_at``, ``review_due_at``).
   The Phase 2 ingestion CLI never set them, so they stay NULL for older rows:
   a NULL means "not recorded", never "verified recently".

2. Seven new tables: techniques (+ crops, regions), evidence classification,
   pesticide information (+ targets) and the shared translation table.

Knowledge rows enter the database only through the reviewed import CLI
(``python -m agriq.cli.import_farming_knowledge``), never from a browser route,
and remain ``PENDING_REVIEW`` until a named reviewer approves them. Downgrade
drops exactly what this revision added, so an upgrade/downgrade round-trip is
lossless for pre-existing data.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0008_farming_knowledge"
down_revision = "0007_auth_sessions"
branch_labels = None
depends_on = None

_SOURCE_TABLE = "knowledge_sources"

#: column name -> column definition, added only when absent.
_NEW_SOURCE_COLUMNS = (
    ("source_type", sa.Column("source_type", sa.String(40), nullable=True)),
    ("accessed_at", sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=True)),
    ("last_verified_at", sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True)),
    ("review_due_at", sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=True)),
)

#: Tables this revision owns, in dependency order.
_NEW_TABLES = (
    "farming_techniques",
    "farming_technique_crops",
    "farming_technique_regions",
    "pesticide_information",
    "farming_knowledge_evidence",
    "farming_pesticide_targets",
    "knowledge_translations",
)


def upgrade() -> None:
    """Create the knowledge-base schema from model metadata (idempotent)."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401  (register all models on the metadata)

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # 1. Additive provenance columns on the shared source table.
    if _SOURCE_TABLE in existing:
        columns = {column["name"] for column in inspector.get_columns(_SOURCE_TABLE)}
        for name, column in _NEW_SOURCE_COLUMNS:
            if name in columns:
                continue
            op.add_column(_SOURCE_TABLE, column)
        indexes = {index["name"] for index in inspector.get_indexes(_SOURCE_TABLE)}
        if "ix_knowledge_sources_source_type" not in indexes:
            op.create_index(
                "ix_knowledge_sources_source_type", _SOURCE_TABLE, ["source_type"]
            )

    # 2. New tables (parents first; metadata create() is checkfirst-safe).
    for table in db.metadata.sorted_tables:
        if table.name in _NEW_TABLES and table.name not in existing:
            table.create(bind=bind)


def downgrade() -> None:
    """Drop only what this revision added."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    for name in reversed(_NEW_TABLES):
        if name in existing and name in db.metadata.tables:
            db.metadata.tables[name].drop(bind=bind, checkfirst=True)

    if _SOURCE_TABLE in existing:
        indexes = {index["name"] for index in inspector.get_indexes(_SOURCE_TABLE)}
        if "ix_knowledge_sources_source_type" in indexes:
            op.drop_index("ix_knowledge_sources_source_type", table_name=_SOURCE_TABLE)
        columns = {column["name"] for column in inspector.get_columns(_SOURCE_TABLE)}
        for name, _column in reversed(_NEW_SOURCE_COLUMNS):
            if name in columns:
                op.drop_column(_SOURCE_TABLE, name)


__all__ = ["revision", "down_revision", "upgrade", "downgrade"]
