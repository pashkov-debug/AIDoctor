"""Неизменяемые серверные снимки медицинского контекста (PostgreSQL JSONB)."""

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class ContextSnapshot(IdMixin, TimestampMixin, Base):
    __tablename__ = "context_snapshots"
    __table_args__ = (Index("ix_context_snapshots_patient_created", "patient_id", "created_at"),)

    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(16), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
