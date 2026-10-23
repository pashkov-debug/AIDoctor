"""UI-4B: версии тестовых структурированных предложений и решения врача."""

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class AIReviewCase(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_review_cases"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_ai_review_case_request"),
        CheckConstraint(
            "status IN ('open','approved','rejected')", name="ck_ai_review_case_status"
        ),
        CheckConstraint("current_version > 0", name="ck_ai_review_case_version"),
    )
    request_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_requests.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_hash: Mapped[str | None] = mapped_column(String(64))
    approved_result: Mapped[dict | None] = mapped_column(JSONB)


class AIReviewVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_review_versions"
    __table_args__ = (UniqueConstraint("case_id", "version", name="uq_ai_review_version"),)
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_review_cases.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    origin: Mapped[str] = mapped_column(String(40), nullable=False, default="synthetic_manual_test")
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False, default="ai_review.v1")
    proposals_json: Mapped[list] = mapped_column(JSONB, nullable=False)


class AIReviewEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_review_events"
    case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_review_cases.id"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
