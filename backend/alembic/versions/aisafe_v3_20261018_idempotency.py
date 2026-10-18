"""Этап 5.3: идемпотентность HTTP POST Safety Alerts.

Revision ID: aisafe_v3_20261018
Revises: aisafe_v2_20261018
"""

import sqlalchemy as sa
from alembic import op

revision = "aisafe_v3_20261018"
down_revision = "aisafe_v2_20261018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_alert_requests",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("key_digest", sa.String(length=64), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["alert_id"], ["safety_alerts.id"]),
        sa.UniqueConstraint(
            "patient_id", "actor_id", "key_digest",
            name="uq_safety_alert_requests_scope_key",
        ),
        sa.UniqueConstraint(
            "alert_id", name="uq_safety_alert_requests_alert"
        ),
        sa.CheckConstraint(
            "length(key_digest) = 64 AND length(request_digest) = 64",
            name="ck_safety_alert_requests_digests",
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Удаление журнала идемпотентности через downgrade запрещено")
