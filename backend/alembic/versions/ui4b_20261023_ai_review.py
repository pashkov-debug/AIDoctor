"""UI-4B: изолированные тестовые структурированные черновики и решения врача.

Revision ID: ui4b_20261023
Revises: ui4a_20261023
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ui4b_20261023"
down_revision = "ui4a_20261023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_review_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("ai_requests.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("approved_hash", sa.String(64)),
        sa.Column("approved_result", postgresql.JSONB()),
        sa.UniqueConstraint("request_id", name="uq_ai_review_case_request"),
        sa.CheckConstraint(
            "status IN ('open','approved','rejected')", name="ck_ai_review_case_status"
        ),
        sa.CheckConstraint("current_version > 0", name="ck_ai_review_case_version"),
    )
    op.create_table(
        "ai_review_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("ai_review_cases.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("origin", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("proposals_json", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("case_id", "version", name="uq_ai_review_version"),
    )
    op.create_index("ix_ai_review_versions_case_id", "ai_review_versions", ["case_id"])
    op.create_table(
        "ai_review_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("ai_review_cases.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_ai_review_events_case_id", "ai_review_events", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_review_events_case_id", table_name="ai_review_events")
    op.drop_table("ai_review_events")
    op.drop_index("ix_ai_review_versions_case_id", table_name="ai_review_versions")
    op.drop_table("ai_review_versions")
    op.drop_table("ai_review_cases")
