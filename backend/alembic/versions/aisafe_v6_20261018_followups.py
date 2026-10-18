"""Этап 5.7: административный контроль просроченных Safety Alerts.

Revision ID: aisafe_v6_20261018
Revises: aisafe_v5_20261018
"""

import sqlalchemy as sa
from alembic import op

revision = "aisafe_v6_20261018"
down_revision = "aisafe_v5_20261018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_followups",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("recipient_user_id", sa.String(length=36), nullable=False),
        sa.Column("route_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["safety_alerts.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["route_id"], ["safety_notification_routes.id"]),
        sa.UniqueConstraint(
            "alert_id", "recipient_user_id", name="uq_safety_followups_alert_recipient"
        ),
    )
    op.create_index(
        "ix_safety_followups_recipient_created",
        "safety_followups",
        ["recipient_user_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Удаление журнала административных follow-up запрещено")
