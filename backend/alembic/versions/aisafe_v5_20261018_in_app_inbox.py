"""Этап 5.6: локальные in_app уведомления, дедупликация по получателю.

Revision ID: aisafe_v5_20261018
Revises: aisafe_v4_20261018
"""

import sqlalchemy as sa
from alembic import op

revision = "aisafe_v5_20261018"
down_revision = "aisafe_v4_20261018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_in_app_notifications",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outbox_id", sa.String(length=36), nullable=False),
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("recipient_user_id", sa.String(length=36), nullable=False),
        sa.Column("route_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["outbox_id"], ["safety_outbox.id"]),
        sa.ForeignKeyConstraint(["alert_id"], ["safety_alerts.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["route_id"], ["safety_notification_routes.id"]),
        sa.UniqueConstraint(
            "outbox_id", "recipient_user_id",
            name="uq_safety_in_app_outbox_recipient",
        ),
    )
    op.create_index(
        "ix_safety_in_app_recipient_created",
        "safety_in_app_notifications", ["recipient_user_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Удаление журнала доставленных in_app уведомлений запрещено")
