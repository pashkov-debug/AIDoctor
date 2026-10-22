"""Только маршруты in_app к подтверждённой учётной записи врача; без адресов."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class SafetyNotificationRoute(IdMixin, TimestampMixin, Base):
    __tablename__ = "safety_notification_routes"
    __table_args__ = (
        UniqueConstraint(
            "patient_id",
            "recipient_user_id",
            "channel",
            name="uq_safety_notification_routes_scope",
        ),
        CheckConstraint("channel = 'in_app'", name="ck_safety_notification_routes_channel"),
        CheckConstraint(
            "NOT enabled OR confirmed_at IS NOT NULL",
            name="ck_safety_notification_routes_confirmation",
        ),
        Index("ix_safety_notification_routes_patient_enabled", "patient_id", "enabled"),
    )

    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    recipient_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="in_app")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SafetyNotificationRouteEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "safety_notification_route_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('enabled', 'disabled')",
            name="ck_safety_notification_route_events_type",
        ),
        Index("ix_safety_notification_route_events_route", "route_id", "created_at"),
    )

    route_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("safety_notification_routes.id"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(12), nullable=False)
