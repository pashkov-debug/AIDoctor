"""UI-3A: ручные структурированные назначения врача и аудит.

Revision ID: ui3a_20261023
Revises: ui2c_20261023
"""

import sqlalchemy as sa
from alembic import op

revision = "ui3a_20261023"
down_revision = "ui2c_20261023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clinical_orders",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("author_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("active_ingredient", sa.String(200)),
        sa.Column("dosage_form", sa.String(120)),
        sa.Column("strength", sa.String(120)),
        sa.Column("dose_value", sa.Numeric(12, 4)),
        sa.Column("dose_unit", sa.String(60)),
        sa.Column("route", sa.String(120)),
        sa.Column("frequency_per_day", sa.Integer()),
        sa.Column("times_local", sa.JSON()),
        sa.Column("timezone", sa.String(80)),
        sa.Column("start_date", sa.Date()),
        sa.Column("duration_days", sa.Integer()),
        sa.Column("administration_notes", sa.String(500)),
        sa.Column("examination_details", sa.String(1000)),
        sa.Column("indication", sa.String(1000)),
        sa.Column("contraindications", sa.String(1000)),
        sa.Column("rationale", sa.String(1500)),
        sa.Column("source_reference", sa.String(500)),
        sa.Column("approved_by_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_by_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.String(500)),
        sa.CheckConstraint("kind IN ('medication','examination')", name="ck_orders_kind"),
        sa.CheckConstraint("status IN ('draft','approved','cancelled')", name="ck_orders_status"),
        sa.CheckConstraint("version > 0", name="ck_orders_version"),
        sa.CheckConstraint("dose_value IS NULL OR dose_value > 0", name="ck_orders_dose_positive"),
        sa.UniqueConstraint("author_id", "request_key", name="uq_orders_author_request"),
    )
    op.create_index("ix_clinical_orders_patient_id", "clinical_orders", ["patient_id"])
    op.create_table(
        "clinical_order_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("clinical_orders.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_clinical_order_audit_order_id", "clinical_order_audit", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_clinical_order_audit_order_id", table_name="clinical_order_audit")
    op.drop_table("clinical_order_audit")
    op.drop_index("ix_clinical_orders_patient_id", table_name="clinical_orders")
    op.drop_table("clinical_orders")
