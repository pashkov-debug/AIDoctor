"""Независимый аудит операций управления доступом UI-1C."""

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class AdminAuditEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "admin_audit_events"

    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    details_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
