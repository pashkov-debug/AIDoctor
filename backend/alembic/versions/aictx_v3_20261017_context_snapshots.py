"""Неизменяемые серверные снимки медицинского контекста.

Revision ID: aictx_v3_20261017
Revises: c103_medical_metadata
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "aictx_v3_20261017"
down_revision = "c103_medical_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "context_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("fact_count", sa.Integer(), nullable=False),
        sa.Column("payload_json", JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
    )
    op.create_index(
        "ix_context_snapshots_patient_created",
        "context_snapshots",
        ["patient_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Удаление медицинских снимков через автоматический downgrade запрещено")
