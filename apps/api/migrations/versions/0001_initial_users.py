"""Phase 1 initial schema: users + full farmer-data foundation.

Revision ID: 0001_initial_users
Revises: -
Create Date: 2026-09-22

Creates every Phase 1 table from the SQLAlchemy metadata (13 tables):
users, farmer_profiles, farms, fields, soil_tests, crop_cycles,
field_observations, weather_snapshots, market_price_records, conversations,
messages, recommendations, farmer_actions.

Schema only — no seed or demo rows are inserted, ever.
"""
from __future__ import annotations

from alembic import op

revision = "0001_initial_users"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the Phase 1 schema from model metadata (idempotent)."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401  (register all models on the metadata)

    db.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    """Drop the Phase 1 schema."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401

    db.metadata.drop_all(bind=op.get_bind())
