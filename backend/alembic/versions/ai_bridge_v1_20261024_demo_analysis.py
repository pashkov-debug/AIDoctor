"""Синтетические ответы внешнего AI-агента без изменения клинических назначений.

Revision ID: ai_bridge_v1_20261024
Revises: ui6a_20261023
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ai_bridge_v1_20261024"
down_revision = "ui6a_20261023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_demo_analyses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("ai_requests.id"), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("doctor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("context_sha256", sa.String(64), nullable=False),
        sa.Column("orders_sha256", sa.String(64), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.CheckConstraint(
            "status = 'draft_requires_review'",
            name="ck_ai_demo_analysis_review_status",
        ),
        sa.CheckConstraint(
            "schema_version = 'aidoctor_demo_analysis.v1'",
            name="ck_ai_demo_analysis_schema_v1",
        ),
        sa.UniqueConstraint("request_id", name="uq_ai_demo_analysis_request"),
    )
    op.create_index("ix_ai_demo_analysis_patient", "ai_demo_analyses", ["patient_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_demo_analysis_patient", table_name="ai_demo_analyses")
    op.drop_table("ai_demo_analyses")
