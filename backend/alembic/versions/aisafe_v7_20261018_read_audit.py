"""Этап 5.8: безопасный журнал фактов чтения Safety API.

Revision ID: aisafe_v7_20261018
Revises: aisafe_v6_20261018
"""

import sqlalchemy as sa
from alembic import op

revision = "aisafe_v7_20261018"
down_revision = "aisafe_v6_20261018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "safety_read_audit",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=True),
        sa.Column("scope", sa.String(length=24), nullable=False),
        sa.Column("returned_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.CheckConstraint(
            "((scope IN ('alerts_list', 'route_read') AND patient_id IS NOT NULL) "
            "OR (scope IN ('inbox_list', 'followups_list') AND patient_id IS NULL))",
            name="ck_safety_read_audit_scope_patient",
        ),
        sa.CheckConstraint(
            "returned_count >= 0 AND returned_count <= 100",
            name="ck_safety_read_audit_count",
        ),
    )
    op.create_index(
        "ix_safety_read_audit_actor_created",
        "safety_read_audit",
        ["actor_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError("Удаление журнала чтений Safety API запрещено")
