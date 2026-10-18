"""PostgreSQL Outbox для ручных Safety Alerts (без канала доставки)."""

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

from app.db.base import Base, IdMixin, TimestampMixin


class SafetyOutbox(IdMixin, TimestampMixin, Base):
    __tablename__ = "safety_outbox"
    __table_args__ = (
        UniqueConstraint("alert_id", "event_type", name="uq_safety_outbox_source_event"),
        CheckConstraint("event_type IN ('created')", name="ck_safety_outbox_event_type"),
        CheckConstraint(
            "status IN ('pending', 'processing', 'delivered', 'failed')",
            name="ck_safety_outbox_status",
        ),
        CheckConstraint(
            "attempt_count >= 0 AND attempt_count <= 3",
            name="ck_safety_outbox_attempt_count",
        ),
        CheckConstraint(
            "(status = 'processing' AND claim_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'processing' AND claim_token IS NULL "
            "AND lease_expires_at IS NULL)",
            name="ck_safety_outbox_lease",
        ),
        CheckConstraint(
            "(status = 'delivered' AND delivered_at IS NOT NULL) OR "
            "(status <> 'delivered' AND delivered_at IS NULL)",
            name="ck_safety_outbox_delivered_at",
        ),
        Index("ix_safety_outbox_due", "status", "next_attempt_at"),
        Index("ix_safety_outbox_lease_expiry", "status", "lease_expires_at"),
    )

    alert_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("safety_alerts.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim_token: Mapped[str | None] = mapped_column(String(36))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(48))


class SafetyOutboxEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "safety_outbox_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('enqueued', 'claimed', 'retry_scheduled', "
            "'delivered', 'exhausted')",
            name="ck_safety_outbox_events_type",
        ),
        CheckConstraint(
            "attempt_number >= 0 AND attempt_number <= 3",
            name="ck_safety_outbox_events_attempt",
        ),
        Index("ix_safety_outbox_events_item_created", "outbox_id", "created_at"),
    )

    outbox_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("safety_outbox.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(48))
