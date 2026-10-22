"""Контролируемое раскрытие исторических событий пациенту, без копирования внутренних фактов."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class ClinicalPublication(IdMixin, TimestampMixin, Base):
    __tablename__ = "clinical_publications"
    __table_args__ = (UniqueConstraint("history_event_id", name="uq_clinical_publication_source"),)

    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id"), index=True, nullable=False
    )
    history_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("history_events.id"), nullable=False, index=True
    )
    confirmed_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="confirmed")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    patient_text: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ClinicalPublicationAudit(IdMixin, TimestampMixin, Base):
    __tablename__ = "clinical_publication_audit"

    publication_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clinical_publications.id"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    details_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
