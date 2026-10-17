from datetime import datetime
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base, IdMixin, TimestampMixin, utc_now

class MedicalObservation(IdMixin, TimestampMixin, Base):
    __tablename__ = "medical_observations"
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False, index=True)
    encounter_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("encounters.id"), nullable=True)
    code_system: Mapped[str | None] = mapped_column(String(100), nullable=True)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    value_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(250), nullable=True)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("medical_observations.id"), nullable=True)

class MedicalAttachment(IdMixin, TimestampMixin, Base):
    __tablename__ = "medical_attachments"
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False, index=True)
    uploaded_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_length: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    extraction_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    extracted_text_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Оригиналы не хранятся в БД; только защищённые storage keys.
