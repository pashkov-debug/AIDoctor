"""Этап 6.1: неизменяемые черновики ручных выдержек, без обработки файлов.

Revision ID: aiextract_v1_20261018
Revises: aisafe_v7_20261018
"""

import sqlalchemy as sa
from alembic import op

revision = "aiextract_v1_20261018"
down_revision = "aisafe_v7_20261018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachment_evidence_drafts",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("attachment_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("attachment_sha256", sa.String(length=64), nullable=False),
        sa.Column("excerpt_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_locator", sa.String(length=120), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["attachment_id"], ["medical_attachments.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.UniqueConstraint(
            "attachment_id",
            "created_by_id",
            "source_locator",
            "excerpt_sha256",
            name="uq_attachment_evidence_draft_identity",
        ),
        sa.CheckConstraint(
            "char_length(source_locator) BETWEEN 1 AND 120",
            name="ck_attachment_evidence_locator_size",
        ),
        sa.CheckConstraint(
            "char_length(excerpt) BETWEEN 1 AND 2000",
            name="ck_attachment_evidence_excerpt_size",
        ),
    )
    op.create_index(
        "ix_attachment_evidence_drafts_patient_created",
        "attachment_evidence_drafts",
        ["patient_id", "created_at"],
    )

    op.create_table(
        "attachment_evidence_read_audit",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("attachment_id", sa.String(length=36), nullable=False),
        sa.Column("returned_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["attachment_id"], ["medical_attachments.id"]),
        sa.CheckConstraint(
            "returned_count >= 0 AND returned_count <= 50",
            name="ck_attachment_evidence_read_audit_count",
        ),
    )
    op.create_index(
        "ix_attachment_evidence_read_audit_actor_created",
        "attachment_evidence_read_audit",
        ["actor_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Автоматическое удаление истории медицинских черновиков запрещено")
