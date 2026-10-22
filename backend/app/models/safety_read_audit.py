"""Минимальный append-only журнал успешных чтений Safety API.

Не хранит клинический текст, токены, тело запроса или содержимое ответа.
"""

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class SafetyReadAudit(IdMixin, TimestampMixin, Base):
    __tablename__ = "safety_read_audit"
    __table_args__ = (
        CheckConstraint(
            "((scope IN ('alerts_list', 'route_read') AND patient_id IS NOT NULL) "
            "OR (scope IN ('inbox_list', 'followups_list') AND patient_id IS NULL))",
            name="ck_safety_read_audit_scope_patient",
        ),
        CheckConstraint(
            "returned_count >= 0 AND returned_count <= 100",
            name="ck_safety_read_audit_count",
        ),
        Index("ix_safety_read_audit_actor_created", "actor_id", "created_at"),
    )

    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    patient_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("patients.id"))
    scope: Mapped[str] = mapped_column(String(24), nullable=False)
    returned_count: Mapped[int] = mapped_column(Integer, nullable=False)
