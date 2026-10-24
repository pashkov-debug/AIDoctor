"""Персональные подключения врачей к Site без доступа к назначениям.

Revision ID: ai_bridge_v2_20261024
Revises: ai_bridge_v1_20261024
"""

import sqlalchemy as sa
from alembic import op

revision = "ai_bridge_v2_20261024"
down_revision = "ai_bridge_v1_20261024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "site_doctor_credentials",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("doctor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("enabled", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_site_doctor_credentials_doctor", "site_doctor_credentials", ["doctor_id"])
    op.create_table(
        "site_doctor_access_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("doctor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("request_id", sa.String(36), sa.ForeignKey("ai_requests.id"), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
    )
    op.create_index(
        "ix_site_doctor_access_audit_doctor",
        "site_doctor_access_audit",
        ["doctor_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_site_doctor_access_audit_doctor", table_name="site_doctor_access_audit")
    op.drop_table("site_doctor_access_audit")
    op.drop_index("ix_site_doctor_credentials_doctor", table_name="site_doctor_credentials")
    op.drop_table("site_doctor_credentials")
