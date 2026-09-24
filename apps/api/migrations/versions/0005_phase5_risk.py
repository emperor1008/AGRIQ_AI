"""Phase 5 risk-intelligence table.

Revision ID: 0005_phase5_risk
Revises: 0004_phase4_image
Create Date: 2026-09-23

Schema only — no seed rows, no fabricated risk history.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_phase5_risk"
down_revision = "0004_phase4_image"
branch_labels = None
depends_on = None

_RISK_TABLES = ("risk_assessments",)


def upgrade() -> None:
    """Create the risk_assessments table from model metadata (idempotent)."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401  (register all models on the metadata)

    bind = op.get_bind()
    existing = set(db.inspect(bind).get_table_names())
    for table in _RISK_TABLES:
        if table in existing:
            continue
        db.metadata.tables[table].create(bind=bind)

    # Dev databases created between migration authoring and the run_group
    # addition: add the missing column instead of failing (additive, safe).
    if "risk_assessments" in existing:
        cols = {c["name"] for c in db.inspect(bind).get_columns("risk_assessments")}
        if "run_group" not in cols:
            op.add_column("risk_assessments", sa.Column("run_group", sa.String(32), nullable=True))
            op.create_index("ix_risk_assessments_run_group", "risk_assessments", ["run_group"])


def downgrade() -> None:
    """Drop the Phase 5 table."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401

    for table in reversed(_RISK_TABLES):
        if table in db.metadata.tables:
            db.metadata.tables[table].drop(bind=op.get_bind(), checkfirst=True)
