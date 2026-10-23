"""UI-4A: подготовленные запросы AI без отправки провайдеру.

Revision ID: ui4a_20261023
Revises: ui3b_20261023
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ui4a_20261023"
down_revision = "ui3b_20261023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("doctor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "context_snapshot_id",
            sa.String(36),
            sa.ForeignKey("context_snapshots.id"),
            nullable=False,
        ),
        sa.Column("context_sha256", sa.String(64), nullable=False),
        sa.Column("doctor_context_json", postgresql.JSONB(), nullable=False),
        sa.Column("attachment_manifest_json", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("doctor_id", "request_key", name="uq_ai_requests_doctor_key"),
        sa.CheckConstraint("status = 'prepared'", name="ck_ai_requests_prepared_only"),
        sa.CheckConstraint("schema_version = 'ai_request.v1'", name="ck_ai_requests_schema_v1"),
        sa.CheckConstraint("revision = 1", name="ck_ai_requests_revision_one"),
    )
    op.create_index("ix_ai_requests_patient_created", "ai_requests", ["patient_id", "created_at"])
    op.create_table(
        "ai_request_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("ai_requests.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event", sa.String(40), nullable=False),
    )
    op.create_index("ix_ai_request_audit_request", "ai_request_audit", ["request_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_request_audit_request", table_name="ai_request_audit")
    op.drop_table("ai_request_audit")
    op.drop_index("ix_ai_requests_patient_created", table_name="ai_requests")
    op.drop_table("ai_requests")
