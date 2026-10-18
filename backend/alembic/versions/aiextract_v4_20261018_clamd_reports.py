"""6.3.1: отчет AV INSTREAM и аудит, без разрешения парсинга.

Revision ID: aiextract_v4_20261018
Revises: aiextract_v3_20261018
"""

import sqlalchemy as sa
from alembic import op

revision = "aiextract_v4_20261018"
down_revision = "aiextract_v3_20261018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attachment_av_scans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column(
            "attachment_id", sa.String(36), sa.ForeignKey("medical_attachments.id"),
            nullable=False,
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content_length", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason_code", sa.String(40), nullable=True),
        sa.Column("engine_name", sa.String(16), nullable=False),
        sa.Column("engine_version", sa.String(200), nullable=True),
        sa.CheckConstraint(
            "status IN ('clean_reported', 'infected_reported', 'error')",
            name="ck_attachment_av_scan_status",
        ),
        sa.CheckConstraint(
            "(status = 'error' AND reason_code IS NOT NULL) OR "
            "(status <> 'error' AND reason_code IS NULL)",
            name="ck_attachment_av_scan_reason",
        ),
        sa.CheckConstraint(
            "content_length BETWEEN 1 AND 20971520", name="ck_attachment_av_scan_size"
        ),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_attachment_av_scan_hash_length"),
    )
    op.create_index(
        "ix_attachment_av_scans_attachment_created",
        "attachment_av_scans", ["attachment_id", "created_at"],
    )
    op.drop_constraint(
        "ck_attachment_security_event_action", "attachment_security_events", type_="check"
    )
    op.create_check_constraint(
        "ck_attachment_security_event_action",
        "attachment_security_events",
        "action IN ('read', 'precheck', 'scan_input', 'av_scan')",
    )


def downgrade() -> None:
    raise RuntimeError(
        "Автоматический downgrade запрещён: события AV и результаты сканирования "
        "содержат важные данные аудита"
    )
