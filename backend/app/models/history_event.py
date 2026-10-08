from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, utc_now


class HistoryEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "history_events"

    patient_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("patients.id"),
        nullable=False,
        index=True,
    )

    encounter_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("encounters.id"),
        nullable=True,
        index=True,
    )

    category: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )

    fact_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )

    priority: Mapped[str] = mapped_column(
        String(20),
        default="normal",
        nullable=False,
    )

    source_ref: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    supersedes_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("history_events.id"),
        nullable=True,
    )

    correction_reason: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
