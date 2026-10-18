"""6.3.0: аудит передачи проверенных байтов из карантина будущему AV.

Revision ID: aiextract_v3_20261018
Revises: aiextract_v2_20261018
"""

from alembic import op

revision = "aiextract_v3_20261018"
down_revision = "aiextract_v2_20261018"
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
        "action IN ('read', 'precheck', 'scan_input')",
    )


def downgrade() -> None:
    raise RuntimeError(
        "Откат аудита невозможен без удаления событий scan_input; "
        "миграция запрещает автоматическую потерю журнала"
    )
