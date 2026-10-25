"""Аудит ручных клинических записей.

Revision ID: workspace_s1_20261025
Revises: ai_bridge_v2_20261024
"""

import sqlalchemy as sa
from alembic import op

revision = "workspace_s1_20261025"
down_revision = "ai_bridge_v2_20261024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clinical_entry_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("record_type", sa.String(40), nullable=False),
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(250), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_clinical_entry_audit_patient_id", "clinical_entry_audit", ["patient_id"])
    op.create_index("ix_clinical_entry_audit_actor_id", "clinical_entry_audit", ["actor_id"])
    op.create_index("ix_clinical_entry_audit_record_id", "clinical_entry_audit", ["record_id"])


def downgrade() -> None:
    op.drop_index("ix_clinical_entry_audit_record_id", table_name="clinical_entry_audit")
    op.drop_index("ix_clinical_entry_audit_actor_id", table_name="clinical_entry_audit")
    op.drop_index("ix_clinical_entry_audit_patient_id", table_name="clinical_entry_audit")
    op.drop_table("clinical_entry_audit")
