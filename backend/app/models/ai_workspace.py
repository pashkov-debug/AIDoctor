"""UI-4A: подготовленные запросы врача, без вызова LLM и ответов AI."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class AIRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_requests"
    __table_args__ = (
        UniqueConstraint("doctor_id", "request_key", name="uq_ai_requests_doctor_key"),
        Index("ix_ai_requests_patient_created", "patient_id", "created_at"),
        CheckConstraint("status = 'prepared'", name="ck_ai_requests_prepared_only"),
        CheckConstraint("schema_version = 'ai_request.v1'", name="ck_ai_requests_schema_v1"),
        CheckConstraint("revision = 1", name="ck_ai_requests_revision_one"),
    )

    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    doctor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    request_key: Mapped[str] = mapped_column(String(36), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False, default="ai_request.v1")
    question: Mapped[str] = mapped_column(Text, nullable=False)
    context_snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("context_snapshots.id"), nullable=False
    )
    context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    doctor_context_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    attachment_manifest_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="prepared")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class AIRequestAudit(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_request_audit"
    __table_args__ = (Index("ix_ai_request_audit_request", "request_id", "created_at"),)

    request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_requests.id"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    event: Mapped[str] = mapped_column(String(40), nullable=False)
