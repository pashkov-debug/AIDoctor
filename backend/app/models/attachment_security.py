"""Карантинные предварительные проверки и не содержащий медданных аудит."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, utc_now


class AttachmentSecurityReview(IdMixin, TimestampMixin, Base):
    """Одна текущая оценка файла; отсутствие записи означает карантин."""

    __tablename__ = "attachment_security_reviews"
    __table_args__ = (
        UniqueConstraint("attachment_id", name="uq_attachment_security_attachment"),
        CheckConstraint(
            "status IN ('prechecked_quarantined', 'rejected')",
            name="ck_attachment_security_review_status",
        ),
        CheckConstraint(
            "(status = 'rejected' AND reason_code IS NOT NULL) OR "
            "(status = 'prechecked_quarantined' AND reason_code IS NULL)",
            name="ck_attachment_security_review_reason",
        ),
        CheckConstraint(
            "checked_length >= 0 AND checked_length <= 20971520",
            name="ck_attachment_security_review_length",
        ),
    )

    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id"), nullable=False
    )
    attachment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("medical_attachments.id"), nullable=False
    )
    checked_by_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    checked_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    checked_length: Mapped[int] = mapped_column(Integer(), nullable=False)


class AttachmentSecurityEvent(IdMixin, TimestampMixin, Base):
    """Аудит запросов: без текста вложения, пути хранения и содержимого."""

    __tablename__ = "attachment_security_events"
    __table_args__ = (
        Index("ix_attachment_security_events_patient_created", "patient_id", "created_at"),
        CheckConstraint(
            "action IN ('read', 'precheck')",
            name="ck_attachment_security_event_action",
        ),
        CheckConstraint(
            "outcome IN ('quarantined', 'prechecked_quarantined', 'rejected', 'error')",
            name="ck_attachment_security_event_outcome",
        ),
    )

    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id"), nullable=False
    )
    attachment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("medical_attachments.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
