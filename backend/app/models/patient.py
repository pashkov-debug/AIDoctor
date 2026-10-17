from datetime import datetime

from sqlalchemy import JSON, DateTime, String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class Patient(IdMixin, TimestampMixin, Base):
    __tablename__ = "patients"

    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True, unique=True)

    alias: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )

    demographics_json: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
