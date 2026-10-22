"""Этап 5.2: транзакционный Outbox и аудит попыток (без отправки).

Revision ID: aisafe_v2_20261018
Revises: aisafe_v1_20261017
"""

import sqlalchemy as sa
from alembic import op

revision = "aisafe_v2_20261018"
down_revision = "aisafe_v1_20261017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_outbox",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_token", sa.String(length=36), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=48), nullable=True),
        sa.ForeignKeyConstraint(["alert_id"], ["safety_alerts.id"]),
        sa.UniqueConstraint("alert_id", "event_type", name="uq_safety_outbox_source_event"),
        sa.CheckConstraint("event_type IN ('created')", name="ck_safety_outbox_event_type"),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'delivered', 'failed')",
            name="ck_safety_outbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 3",
            name="ck_safety_outbox_attempt_count",
        ),
        sa.CheckConstraint(
            "(status = 'processing' AND claim_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'processing' AND claim_token IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_safety_outbox_lease",
        ),
        sa.CheckConstraint(
            "(status = 'delivered' AND delivered_at IS NOT NULL) OR "
            "(status <> 'delivered' AND delivered_at IS NULL)",
            name="ck_safety_outbox_delivered_at",
        ),
    )
    op.create_index(
        "ix_safety_outbox_due",
        "safety_outbox",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "ix_safety_outbox_lease_expiry",
        "safety_outbox",
        ["status", "lease_expires_at"],
    )
    op.create_table(
        "safety_outbox_events",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outbox_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=48), nullable=True),
        sa.ForeignKeyConstraint(["outbox_id"], ["safety_outbox.id"]),
        sa.CheckConstraint(
            "event_type IN ('enqueued', 'claimed', 'retry_scheduled', 'delivered', 'exhausted')",
            name="ck_safety_outbox_events_type",
        ),
        sa.CheckConstraint(
            "attempt_number >= 0 AND attempt_number <= 3",
            name="ck_safety_outbox_events_attempt",
        ),
    )
    op.create_index(
        "ix_safety_outbox_events_item_created",
        "safety_outbox_events",
        ["outbox_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Удаление Outbox и аудита доставки через downgrade запрещено")
