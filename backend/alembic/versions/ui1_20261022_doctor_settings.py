"""UI-1: настройки врача, версии и журнал изменений.

Revision ID: ui1_20261022
Revises: aiextract_v5_20261019
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "ui1_20261022"
down_revision = "aiextract_v5_20261019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "doctor_settings",
        sa.Column(
            "doctor_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(160)),
        sa.Column("specialty", sa.String(120)),
        sa.Column("institution", sa.String(200)),
        sa.Column("professional_info", sa.String(2000)),
        sa.Column("contact_email", sa.String(254)),
        sa.Column("practice_country", sa.String(120)),
        sa.Column("rki_mode", sa.String(32), nullable=False),
        sa.Column("institution_type", sa.String(120)),
        sa.Column("clinical_specialty", sa.String(120)),
        sa.CheckConstraint("version >= 1", name="ck_doctor_settings_version"),
        sa.CheckConstraint(
            "rki_mode IN ('disabled', 'consider_if_verified')",
            name="ck_doctor_settings_rki_mode",
        ),
    )
    op.create_table(
        "doctor_settings_audit",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "doctor_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("section", sa.String(20), nullable=False),
        sa.Column("from_version", sa.Integer(), nullable=False),
        sa.Column("to_version", sa.Integer(), nullable=False),
        sa.Column("changed_fields", JSONB(), nullable=False),
    )
    op.create_index("ix_doctor_settings_audit_doctor_id", "doctor_settings_audit", ["doctor_id"])


def downgrade() -> None:
    raise RuntimeError("Downgrade настроек врача запрещён: сохраните медицинские настройки и аудит")
