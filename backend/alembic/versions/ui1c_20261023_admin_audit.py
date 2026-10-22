"""UI-1C: аудит административных изменений.

Revision ID: ui1c_20261023
Revises: ui1_20261022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ui1c_20261023"
down_revision: str | Sequence[str] | None = "ui1_20261022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_admin_audit_events_actor_id", "admin_audit_events", ["actor_id"])


def downgrade() -> None:
    op.drop_index("ix_admin_audit_events_actor_id", table_name="admin_audit_events")
    op.drop_table("admin_audit_events")
