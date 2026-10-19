"""6.4.0: разрешить отдельный аудит снимков кандидатов для CDR.

Revision ID: aiextract_v5_20261019
Revises: aiextract_v4_20261018
"""

from alembic import op

revision = "aiextract_v5_20261019"
down_revision = "aiextract_v4_20261018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_attachment_security_event_action",
        "attachment_security_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_attachment_security_event_action",
        "attachment_security_events",
        "action IN ('read', 'precheck', 'scan_input', 'av_scan', 'cdr_input')",
    )


def downgrade() -> None:
    raise RuntimeError(
        "Откат запрещён: события cdr_input являются частью аудита и "
        "не могут быть автоматически отброшены"
    )
