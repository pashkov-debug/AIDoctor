"""Внутренние уведомления Safety Alerts: запись подтверждена PostgreSQL.

Хранит только технические идентификаторы; не содержит текстов/диагнозов.
"""

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class SafetyInAppNotification(IdMixin, TimestampMixin, Base):
    __tablename__ = "safety_in_app_notifications"
    __table_args__ = (
        UniqueConstraint(
            "outbox_id",
            "recipient_user_id",
            name="uq_safety_in_app_outbox_recipient",
        ),
        Index(
            "ix_safety_in_app_recipient_created",
            "recipient_user_id",
            "created_at",
        ),
    )

    outbox_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("safety_outbox.id"), nullable=False
    )
    alert_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("safety_alerts.id"), nullable=False
    )
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    recipient_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    route_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("safety_notification_routes.id"), nullable=False
    )
