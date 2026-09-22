"""Phase 3 voice tables: consents, sessions, transcripts, synthesised audio.

Revision ID: 0003_phase3_voice
Revises: 0002_phase2_copilot
Create Date: 2026-09-23

Schema only — no seed rows, no consent records, no audio metadata. Consent
rows are created only when a real farmer consents through the API.
"""
from __future__ import annotations

from alembic import op

revision = "0003_phase3_voice"
down_revision = "0002_phase2_copilot"
branch_labels = None
depends_on = None

_VOICE_TABLES = (
    "synthesised_audio",
    "transcripts",
    "voice_sessions",
    "voice_consents",
)


def upgrade() -> None:
    """Create the Phase 3 tables from model metadata (idempotent)."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401  (register all models on the metadata)

    existing = set(db.inspect(op.get_bind()).get_table_names())
    for table in _VOICE_TABLES:
        if table in existing:
            continue
        db.metadata.tables[table].create(bind=op.get_bind())


def downgrade() -> None:
    """Drop the Phase 3 tables."""
    from agriq.extensions import db
    import agriq.models  # noqa: F401

    for table in reversed(_VOICE_TABLES):
        if table in db.metadata.tables:
            db.metadata.tables[table].drop(bind=op.get_bind(), checkfirst=True)
