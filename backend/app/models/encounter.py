from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, utc_now


class Encounter(IdMixin, TimestampMixin, Base):
    __tablename__ = "encounters"

    patient_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("patients.id"),
        nullable=False,
        index=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )

    reason: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="draft",
        nullable=False,
    )

    payload_json: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
