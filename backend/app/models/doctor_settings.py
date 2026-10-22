"""Персональные и клинические настройки врача; аудит без копий персональных полей."""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, utc_now


class DoctorSettings(Base):
    __tablename__ = "doctor_settings"
    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_doctor_settings_version"),
        CheckConstraint(
            "rki_mode IN ('disabled', 'consider_if_verified')",
            name="ck_doctor_settings_rki_mode",
        ),
    )

    doctor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(160))
    specialty: Mapped[str | None] = mapped_column(String(120))
    institution: Mapped[str | None] = mapped_column(String(200))
    professional_info: Mapped[str | None] = mapped_column(String(2000))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    practice_country: Mapped[str | None] = mapped_column(String(120))
    rki_mode: Mapped[str] = mapped_column(String(32), default="disabled", nullable=False)
    institution_type: Mapped[str | None] = mapped_column(String(120))
    clinical_specialty: Mapped[str | None] = mapped_column(String(120))


class DoctorSettingsAudit(IdMixin, TimestampMixin, Base):
    __tablename__ = "doctor_settings_audit"
    doctor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    section: Mapped[str] = mapped_column(String(20), nullable=False)
    from_version: Mapped[int] = mapped_column(Integer, nullable=False)
    to_version: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_fields: Mapped[list] = mapped_column(JSONB, nullable=False)
