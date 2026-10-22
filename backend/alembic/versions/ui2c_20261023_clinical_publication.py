"""UI-2C: подтверждение истории и контролируемые публикации пациенту.

Revision ID: ui2c_20261023
Revises: ui1c_20261023
"""

import sqlalchemy as sa
from alembic import op

revision = "ui2c_20261023"
down_revision = "ui1c_20261023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clinical_publications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column(
            "history_event_id", sa.String(36), sa.ForeignKey("history_events.id"), nullable=False
        ),
        sa.Column("confirmed_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("patient_text", sa.String(2000), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("revoke_reason", sa.String(500), nullable=True),
        sa.UniqueConstraint("history_event_id", name="uq_clinical_publication_source"),
    )
    op.create_index("ix_clinical_publications_patient_id", "clinical_publications", ["patient_id"])
    op.create_index(
        "ix_clinical_publications_history_event_id", "clinical_publications", ["history_event_id"]
    )
    op.create_table(
        "clinical_publication_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "publication_id",
            sa.String(36),
            sa.ForeignKey("clinical_publications.id"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_clinical_publication_audit_publication_id",
        "clinical_publication_audit",
        ["publication_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_clinical_publication_audit_publication_id", table_name="clinical_publication_audit"
    )
    op.drop_table("clinical_publication_audit")
    op.drop_index("ix_clinical_publications_history_event_id", table_name="clinical_publications")
    op.drop_index("ix_clinical_publications_patient_id", table_name="clinical_publications")
    op.drop_table("clinical_publications")
