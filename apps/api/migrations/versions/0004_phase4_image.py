"""Phase 4 image-intelligence tables: analyses + feedback.

Revision ID: 0004_phase4_image
Revises: 0003_phase3_voice
Create Date: 2026-09-23

Schema only — no seed rows, no fabricated analyses. Farmer feedback is never
written as an expert label (separate columns, separate workflow).
"""
from __future__ import annotations

from alembic import op

revision = "0004_phase4_image"
down_revision = "0003_phase3_voice"
branch_labels = None
depends_on = None

_IMAGE_TABLES = (
    "image_analysis_feedback",
    "image_analyses",
)


def upgrade() -> None:
    """Create the Phase 4 tables from model metadata (idempotent)."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401  (register all models on the metadata)

    existing = set(db.inspect(op.get_bind()).get_table_names())
    for table in _IMAGE_TABLES:
        if table in existing:
            continue
        db.metadata.tables[table].create(bind=op.get_bind())


def downgrade() -> None:
    """Drop the Phase 4 tables."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401

    for table in reversed(_IMAGE_TABLES):
        if table in db.metadata.tables:
            db.metadata.tables[table].drop(bind=op.get_bind(), checkfirst=True)
