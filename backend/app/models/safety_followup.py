"""Административные follow-up для непросмотренных ручных Safety Alerts.

Строка — неизменяемое событие постановки в контрольный список,
а не медицинский триаж или повторная доставка.
"""

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class SafetyFollowup(IdMixin, TimestampMixin, Base):
    __tablename__ = "safety_followups"
    __table_args__ = (
        UniqueConstraint(
            "alert_id", "recipient_user_id", name="uq_safety_followups_alert_recipient"
        ),
        Index(
            "ix_safety_followups_recipient_created",
            "recipient_user_id", "created_at",
        ),
    )

    alert_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("safety_alerts.id"), nullable=False
    )
    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id"), nullable=False
    )
    recipient_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    route_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("safety_notification_routes.id"), nullable=False
    )
