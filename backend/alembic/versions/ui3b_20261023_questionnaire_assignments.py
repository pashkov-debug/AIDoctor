"""UI-3B: учебные назначения психологических опросников.

Revision ID: ui3b_20261023
Revises: ui3a_20261023
"""

import sqlalchemy as sa
from alembic import op

revision = "ui3b_20261023"
down_revision = "ui3a_20261023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "questionnaire_assignments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("assigned_by_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("test_id", sa.String(50), nullable=False),
        sa.Column("test_version", sa.String(30), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.String(500)),
        sa.UniqueConstraint(
            "assigned_by_id", "request_key", name="uq_questionnaire_assignment_key"
        ),
        sa.CheckConstraint(
            "status IN ('assigned','completed','cancelled')",
            name="ck_questionnaire_assignment_status",
        ),
        sa.CheckConstraint("revision > 0", name="ck_questionnaire_assignment_revision"),
    )
    op.create_index(
        "ix_questionnaire_assignments_patient_id", "questionnaire_assignments", ["patient_id"]
    )
    op.create_table(
        "questionnaire_submissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "assignment_id",
            sa.String(36),
            sa.ForeignKey("questionnaire_assignments.id"),
            nullable=False,
        ),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("answers_json", sa.JSON(), nullable=False),
        sa.Column("total_score", sa.Integer(), nullable=False),
        sa.Column("critical_flag", sa.Boolean(), nullable=False),
        sa.Column("alert_id", sa.String(36), sa.ForeignKey("safety_alerts.id")),
        sa.UniqueConstraint("assignment_id", name="uq_questionnaire_submission_assignment"),
    )
    op.create_index(
        "ix_questionnaire_submissions_patient_id", "questionnaire_submissions", ["patient_id"]
    )
    op.create_table(
        "questionnaire_assignment_audit",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "assignment_id",
            sa.String(36),
            sa.ForeignKey("questionnaire_assignments.id"),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_questionnaire_assignment_audit_assignment_id",
        "questionnaire_assignment_audit",
        ["assignment_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_questionnaire_assignment_audit_assignment_id",
        table_name="questionnaire_assignment_audit",
    )
    op.drop_table("questionnaire_assignment_audit")
    op.drop_index("ix_questionnaire_submissions_patient_id", table_name="questionnaire_submissions")
    op.drop_table("questionnaire_submissions")
    op.drop_index("ix_questionnaire_assignments_patient_id", table_name="questionnaire_assignments")
    op.drop_table("questionnaire_assignments")
