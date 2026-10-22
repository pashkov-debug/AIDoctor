"""Этап 6.2: метаданные карантинной предпроверки и аудит без AV.

Revision ID: aiextract_v2_20261018
Revises: aiextract_v1_20261018
"""

import sqlalchemy as sa
from alembic import op

revision = "aiextract_v2_20261018"
down_revision = "aiextract_v1_20261018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachment_security_reviews",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column(
            "attachment_id",
            sa.String(36),
            sa.ForeignKey("medical_attachments.id"),
            nullable=False,
        ),
        sa.Column("checked_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(40), nullable=True),
        sa.Column("checked_sha256", sa.String(64), nullable=False),
        sa.Column("checked_length", sa.Integer(), nullable=False),
        sa.UniqueConstraint("attachment_id", name="uq_attachment_security_attachment"),
        sa.CheckConstraint(
            "status IN ('prechecked_quarantined', 'rejected')",
            name="ck_attachment_security_review_status",
        ),
        sa.CheckConstraint(
            "(status = 'rejected' AND reason_code IS NOT NULL) OR "
            "(status = 'prechecked_quarantined' AND reason_code IS NULL)",
            name="ck_attachment_security_review_reason",
        ),
        sa.CheckConstraint(
            "checked_length >= 0 AND checked_length <= 20971520",
            name="ck_attachment_security_review_length",
        ),
    )
    op.create_table(
        "attachment_security_events",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column(
            "attachment_id",
            sa.String(36),
            sa.ForeignKey("medical_attachments.id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("reason_code", sa.String(40), nullable=True),
        sa.CheckConstraint(
            "action IN ('read', 'precheck')", name="ck_attachment_security_event_action"
        ),
        sa.CheckConstraint(
            "outcome IN ('quarantined', 'prechecked_quarantined', 'rejected', 'error')",
            name="ck_attachment_security_event_outcome",
        ),
    )
    op.create_index(
        "ix_attachment_security_events_patient_created",
        "attachment_security_events",
        ["patient_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Автоматическое удаление аудита и истории проверок запрещено")
