"""Generic observations and attachment metadata; no file upload API yet."""

import sqlalchemy as sa
from alembic import op

revision = "c103_medical_metadata"
down_revision = "c102_stage12_auth"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "medical_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("encounter_id", sa.String(36), sa.ForeignKey("encounters.id")),
        sa.Column("code_system", sa.String(100)),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("source_ref", sa.String(250)),
        sa.Column("supersedes_id", sa.String(36), sa.ForeignKey("medical_observations.id")),
    )
    op.create_index("ix_medical_observations_patient_id", "medical_observations", ["patient_id"])
    op.create_table(
        "medical_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("uploaded_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content_length", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(256), nullable=False, unique=True),
        sa.Column("extraction_status", sa.String(24), nullable=False),
        sa.Column("extracted_text_ref", sa.String(256)),
    )
    op.create_index("ix_medical_attachments_patient_id", "medical_attachments", ["patient_id"])


def downgrade():
    op.drop_index("ix_medical_attachments_patient_id", table_name="medical_attachments")
    op.drop_table("medical_attachments")
    op.drop_index("ix_medical_observations_patient_id", table_name="medical_observations")
    op.drop_table("medical_observations")
