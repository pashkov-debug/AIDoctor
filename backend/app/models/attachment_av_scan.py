"""Результаты AV INSTREAM для точных SHA-256, без содержимого документов."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class AttachmentAVScan(IdMixin, TimestampMixin, Base):
    __tablename__ = "attachment_av_scans"
    __table_args__ = (
        Index("ix_attachment_av_scans_attachment_created", "attachment_id", "created_at"),
        CheckConstraint(
            "status IN ('clean_reported', 'infected_reported', 'error')",
            name="ck_attachment_av_scan_status",
        ),
        CheckConstraint(
            "(status = 'error' AND reason_code IS NOT NULL) OR "
            "(status <> 'error' AND reason_code IS NULL)",
            name="ck_attachment_av_scan_reason",
        ),
        CheckConstraint("content_length BETWEEN 1 AND 20971520", name="ck_attachment_av_scan_size"),
        CheckConstraint("length(content_sha256) = 64", name="ck_attachment_av_scan_hash_length"),
    )
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    attachment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("medical_attachments.id"), nullable=False
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_length: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    engine_name: Mapped[str] = mapped_column(String(16), nullable=False, default="clamd")
    # Строка получена по протоколу: НЕ аттестация подлинности движка/баз.
    engine_version: Mapped[str | None] = mapped_column(String(200), nullable=True)
