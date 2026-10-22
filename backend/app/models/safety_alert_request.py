"""Идемпотентность HTTP-создания Safety Alert; ключи хранятся только как SHA-256."""

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class SafetyAlertRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "safety_alert_requests"
    __table_args__ = (
        UniqueConstraint(
            "patient_id",
            "actor_id",
            "key_digest",
            name="uq_safety_alert_requests_scope_key",
        ),
        UniqueConstraint("alert_id", name="uq_safety_alert_requests_alert"),
        CheckConstraint(
            "length(key_digest) = 64 AND length(request_digest) = 64",
            name="ck_safety_alert_requests_digests",
        ),
    )

    patient_id: Mapped[str] = mapped_column(String(36), ForeignKey("patients.id"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    alert_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("safety_alerts.id"), nullable=False
    )
    key_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    request_digest: Mapped[str] = mapped_column(String(64), nullable=False)
