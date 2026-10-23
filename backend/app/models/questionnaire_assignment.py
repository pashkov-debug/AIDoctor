"""Назначения учебных тестов, однократные ответы и неизменяемый аудит."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class QuestionnaireAssignment(IdMixin, TimestampMixin, Base):
    __tablename__ = "questionnaire_assignments"
    __table_args__ = (
        UniqueConstraint("assigned_by_id", "request_key", name="uq_questionnaire_assignment_key"),
        CheckConstraint(
            "status IN ('assigned','completed','cancelled')",
            name="ck_questionnaire_assignment_status",
        ),
        CheckConstraint("revision > 0", name="ck_questionnaire_assignment_revision"),
    )

    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id"), nullable=False, index=True
    )
    assigned_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    request_key: Mapped[str] = mapped_column(String(36), nullable=False)
    test_id: Mapped[str] = mapped_column(String(50), nullable=False)
    test_version: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="assigned")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))


class QuestionnaireSubmission(IdMixin, TimestampMixin, Base):
    __tablename__ = "questionnaire_submissions"
    __table_args__ = (
        UniqueConstraint("assignment_id", name="uq_questionnaire_submission_assignment"),
    )
    assignment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("questionnaire_assignments.id"), nullable=False
    )
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id"), nullable=False, index=True
    )
    answers_json: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    critical_flag: Mapped[bool] = mapped_column(nullable=False, default=False)
    alert_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("safety_alerts.id"))


class QuestionnaireAssignmentAudit(IdMixin, TimestampMixin, Base):
    __tablename__ = "questionnaire_assignment_audit"
    assignment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("questionnaire_assignments.id"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
