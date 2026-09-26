"""Phase 5 follow-up: assessment provenance + evaluation dimensions on risk_assessments.

Revision ID: 0006_risk_provenance
Revises: 0005_phase5_risk
Create Date: 2026-09-24

Additive and idempotent. Two groups of columns:

1. Provenance of the produced number (§7, §17) — ``assessment_method``,
   ``probability_kind``, ``calibration_status``. Rows created before this
   revision were all produced by the deterministic rule engine
   (``rule_version`` is present on every row), so the server defaults
   (``rule_based`` / ``rule_score`` / ``not_validated``) describe them
   truthfully. No fabricated history is written.

2. Evaluation dimensions (§13) — ``crop_name``, ``growth_stage``,
   ``district`` snapshot the context at assessment time so per-crop /
   per-stage / per-district evaluation does not have to re-derive context
   that may have changed since.

Schema only — no seed rows.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_risk_provenance"
down_revision = "0005_phase5_risk"
branch_labels = None
depends_on = None

TABLE = "risk_assessments"

#: column name -> column definition (added only when absent).
_NEW_COLUMNS = (
    (
        "assessment_method",
        sa.Column("assessment_method", sa.String(20), nullable=False, server_default="rule_based"),
    ),
    # No server default here: rows without a probability must keep NULL, and a
    # default would silently mislabel them as rule scores.
    ("probability_kind", sa.Column("probability_kind", sa.String(40), nullable=True)),
    (
        "calibration_status",
        sa.Column("calibration_status", sa.String(20), nullable=False, server_default="not_validated"),
    ),
    ("crop_name", sa.Column("crop_name", sa.String(60), nullable=True)),
    ("growth_stage", sa.Column("growth_stage", sa.String(60), nullable=True)),
    ("district", sa.Column("district", sa.String(80), nullable=True)),
)


def upgrade() -> None:
    """Add the provenance / evaluation-dimension columns when missing."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        # The Phase 5 table has not been created yet on this database; 0005
        # creates it from current model metadata, so there is nothing to alter.
        return

    existing = {column["name"] for column in inspector.get_columns(TABLE)}
    for name, column in _NEW_COLUMNS:
        if name in existing:
            continue
        op.add_column(TABLE, column)

    # Backfill only what the stored data actually proves: every row carrying a
    # probability was produced by the deterministic rule engine
    # (``rule_version`` is set on every row). Rows without a probability keep
    # NULL rather than being labelled with a probability kind they never had.
    if "probability_kind" not in existing:
        op.execute(
            f"UPDATE {TABLE} SET probability_kind = 'rule_score' WHERE probability IS NOT NULL"
        )

    indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    for index_name, column_name in (
        ("ix_risk_assessments_crop_name", "crop_name"),
        ("ix_risk_assessments_district", "district"),
    ):
        if index_name not in indexes:
            op.create_index(index_name, TABLE, [column_name])


def downgrade() -> None:
    """Drop only the columns introduced by this revision."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return

    existing = {column["name"] for column in inspector.get_columns(TABLE)}
    indexes = {index["name"] for index in inspector.get_indexes(TABLE)}
    for index_name in ("ix_risk_assessments_crop_name", "ix_risk_assessments_district"):
        if index_name in indexes:
            op.drop_index(index_name, table_name=TABLE)
    for name, _column in reversed(_NEW_COLUMNS):
        if name in existing:
            op.drop_column(TABLE, name)
