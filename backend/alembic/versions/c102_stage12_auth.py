"""Roles and access control; stage 1-2

Revision ID: c102_stage12_auth
Revises: bb442bccae1b
"""
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "c102_stage12_auth"
down_revision: str | Sequence[str] | None = "bb442bccae1b"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table("users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("username", sa.String(120), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("role", sa.String(20), nullable=False))
    op.create_table("doctor_patients",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("doctor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("patient_id", sa.String(36), sa.ForeignKey("patients.id"), nullable=False),
        sa.UniqueConstraint("doctor_id", "patient_id", name="uq_doctor_patient"))
    op.create_index("ix_doctor_patients_doctor_id", "doctor_patients", ["doctor_id"])
    op.create_index("ix_doctor_patients_patient_id", "doctor_patients", ["patient_id"])
    op.create_table("auth_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    with op.batch_alter_table("patients") as batch:
        batch.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_patients_user_id", "users", ["user_id"], ["id"])
        batch.create_unique_constraint("uq_patients_user_id", ["user_id"])

def downgrade() -> None:
    with op.batch_alter_table("patients") as batch:
        batch.drop_constraint("uq_patients_user_id", type_="unique")
        batch.drop_constraint("fk_patients_user_id", type_="foreignkey")
        batch.drop_column("user_id")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_doctor_patients_patient_id", table_name="doctor_patients")
    op.drop_index("ix_doctor_patients_doctor_id", table_name="doctor_patients")
    op.drop_table("doctor_patients")
    op.drop_table("users")
