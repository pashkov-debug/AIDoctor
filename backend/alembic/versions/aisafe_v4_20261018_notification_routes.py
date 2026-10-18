"""Этап 5.5: добровольные in_app-маршруты врача и аудит переключений.

Revision ID: aisafe_v4_20261018
Revises: aisafe_v3_20261018
"""

import sqlalchemy as sa
from alembic import op

revision = "aisafe_v4_20261018"
down_revision = "aisafe_v3_20261018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_notification_routes",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("recipient_user_id", sa.String(length=36), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["recipient_user_id"], ["users.id"]),
        sa.UniqueConstraint(
            "patient_id", "recipient_user_id", "channel",
            name="uq_safety_notification_routes_scope",
        ),
        sa.CheckConstraint(
            "channel = 'in_app'", name="ck_safety_notification_routes_channel"
        ),
        sa.CheckConstraint(
            "NOT enabled OR confirmed_at IS NOT NULL",
            name="ck_safety_notification_routes_confirmation",
        ),
    )
    op.create_index(
        "ix_safety_notification_routes_patient_enabled",
        "safety_notification_routes", ["patient_id", "enabled"],
    )
    op.create_table(
        "safety_notification_route_events",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("route_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=12), nullable=False),
        sa.ForeignKeyConstraint(["route_id"], ["safety_notification_routes.id"]),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.CheckConstraint(
            "event_type IN ('enabled', 'disabled')",
            name="ck_safety_notification_route_events_type",
        ),
    )
    op.create_index(
        "ix_safety_notification_route_events_route",
        "safety_notification_route_events", ["route_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Удаление аудита настроек оповещений запрещено")
