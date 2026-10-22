"""Неизменяемые черновики ручных выдержек с проверяемым происхождением."""

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class AttachmentEvidenceDraft(IdMixin, TimestampMixin, Base):
    __tablename__ = "attachment_evidence_drafts"
    __table_args__ = (
        UniqueConstraint(
            "attachment_id",
            "created_by_id",
            "source_locator",
            "excerpt_sha256",
            name="uq_attachment_evidence_draft_identity",
        ),
        Index("ix_attachment_evidence_drafts_patient_created", "patient_id", "created_at"),
        CheckConstraint(
            "char_length(source_locator) BETWEEN 1 AND 120",
            name="ck_attachment_evidence_locator_size",
        ),
        CheckConstraint(
            "char_length(excerpt) BETWEEN 1 AND 2000",
            name="ck_attachment_evidence_excerpt_size",
        ),
    )

    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    attachment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("medical_attachments.id"), nullable=False
    )
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    attachment_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    excerpt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_locator: Mapped[str] = mapped_column(String(120), nullable=False)
    excerpt: Mapped[str] = mapped_column(Text(), nullable=False)

    # Неизменяемый текст — предложение врача, не результат AV/OCR или верификации.
    # Статус review находится за пределами этого инкремента.


class AttachmentEvidenceReadAudit(IdMixin, TimestampMixin, Base):
    """Только метаданные успешного чтения; без выдержек и клинического текста."""

    __tablename__ = "attachment_evidence_read_audit"
    __table_args__ = (
        Index("ix_attachment_evidence_read_audit_actor_created", "actor_id", "created_at"),
        CheckConstraint(
            "returned_count >= 0 AND returned_count <= 50",
            name="ck_attachment_evidence_read_audit_count",
        ),
    )

    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    attachment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("medical_attachments.id"), nullable=False
    )
    returned_count: Mapped[int] = mapped_column(Integer(), nullable=False)
