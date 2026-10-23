"""UI-6A: фиксированный перечень утверждённых и предложенных назначений.

Revision ID: ui6a_20261023
Revises: ui4b_20261023
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "ui6a_20261023"
down_revision = "ui4b_20261023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_requests", sa.Column("review_orders_json", postgresql.JSONB(), nullable=True))
    op.add_column("ai_requests", sa.Column("review_orders_sha256", sa.String(64), nullable=True))
    op.create_check_constraint(
        "ck_ai_requests_review_orders_pair",
        "ai_requests",
        "(review_orders_json IS NULL AND review_orders_sha256 IS NULL) OR "
        "(review_orders_json IS NOT NULL AND review_orders_sha256 IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ai_requests_review_orders_pair", "ai_requests", type_="check")
    op.drop_column("ai_requests", "review_orders_sha256")
    op.drop_column("ai_requests", "review_orders_json")
