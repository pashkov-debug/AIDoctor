"""Ручные сигналы для врачебной проверки и минимальный журнал действий."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class SafetyAlert(IdMixin, TimestampMixin, Base):
    __tablename__ = "safety_alerts"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'acknowledged')", name="ck_safety_alerts_status"),
        CheckConstraint("priority IN ('standard', 'urgent')", name="ck_safety_alerts_priority"),
        CheckConstraint(
            "reason_code IN ('clinician_review', 'care_coordination', 'urgent_attention')",
            name="ck_safety_alerts_reason",
        ),
        Index("ix_safety_alerts_patient_status_created", "patient_id", "status", "created_at"),
    )

    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    priority: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))


class SafetyAlertEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "safety_alert_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'acknowledged')",
            name="ck_safety_alert_events_type",
        ),
        Index("ix_safety_alert_events_alert_created", "alert_id", "created_at"),
    )

    alert_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("safety_alerts.id"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
