"""Этап 5.1: ручные сигналы и журнал подтверждений.

Revision ID: aisafe_v1_20261017
Revises: aictx_v3_20261017
"""

import sqlalchemy as sa
from alembic import op

revision = "aisafe_v1_20261017"
down_revision = "aictx_v3_20261017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_alerts",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.String(length=12), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by_id", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["acknowledged_by_id"], ["users.id"]),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged')",
            name="ck_safety_alerts_status",
        ),
        sa.CheckConstraint(
            "priority IN ('standard', 'urgent')",
            name="ck_safety_alerts_priority",
        ),
        sa.CheckConstraint(
            "reason_code IN ('clinician_review', 'care_coordination', 'urgent_attention')",
            name="ck_safety_alerts_reason",
        ),
    )
    op.create_index(
        "ix_safety_alerts_patient_status_created",
        "safety_alerts",
        ["patient_id", "status", "created_at"],
    )
    op.create_table(
        "safety_alert_events",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["safety_alerts.id"]),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.CheckConstraint(
            "event_type IN ('created', 'acknowledged')",
            name="ck_safety_alert_events_type",
        ),
    )
    op.create_index(
        "ix_safety_alert_events_alert_created",
        "safety_alert_events",
        ["alert_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Удаление журнала безопасности через downgrade запрещено")
