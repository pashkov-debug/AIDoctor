"""Серверные ключи врачей для интеграции с Site; секреты в БД не храним."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class SiteDoctorCredential(IdMixin, TimestampMixin, Base):
    __tablename__ = "site_doctor_credentials"
    __table_args__ = (Index("ix_site_doctor_credentials_doctor", "doctor_id"),)

    doctor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SiteDoctorAccessAudit(IdMixin, TimestampMixin, Base):
    __tablename__ = "site_doctor_access_audit"
    __table_args__ = (Index("ix_site_doctor_access_audit_doctor", "doctor_id", "created_at"),)

    doctor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_requests.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
