"""Изолированное хранение результатов анализа, присланных внешним агентом."""

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class AIDemoAnalysis(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_demo_analyses"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_ai_demo_analysis_request"),
        Index("ix_ai_demo_analysis_patient", "patient_id"),
        CheckConstraint(
            "status = 'draft_requires_review'", name="ck_ai_demo_analysis_review_status"
        ),
        CheckConstraint(
            "schema_version = 'aidoctor_demo_analysis.v1'",
            name="ck_ai_demo_analysis_schema_v1",
        ),
    )

    request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_requests.id"), nullable=False
    )
    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    doctor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    context_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    orders_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    schema_version: Mapped[str] = mapped_column(
        String(40), nullable=False, default="aidoctor_demo_analysis.v1"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft_requires_review")
