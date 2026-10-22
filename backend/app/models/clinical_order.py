"""Ручные назначения врача. До утверждения не видны пациенту."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class ClinicalOrder(IdMixin, TimestampMixin, Base):
    __tablename__ = "clinical_orders"
    __table_args__ = (
        UniqueConstraint("author_id", "request_key", name="uq_orders_author_request"),
        CheckConstraint("kind IN ('medication','examination')", name="ck_orders_kind"),
        CheckConstraint("status IN ('draft','approved','cancelled')", name="ck_orders_status"),
        CheckConstraint("version > 0", name="ck_orders_version"),
        CheckConstraint("dose_value IS NULL OR dose_value > 0", name="ck_orders_dose_positive"),
    )

    patient_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("patients.id"), nullable=False, index=True
    )
    author_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    request_key: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    active_ingredient: Mapped[str | None] = mapped_column(String(200))
    dosage_form: Mapped[str | None] = mapped_column(String(120))
    strength: Mapped[str | None] = mapped_column(String(120))
    dose_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    dose_unit: Mapped[str | None] = mapped_column(String(60))
    route: Mapped[str | None] = mapped_column(String(120))
    frequency_per_day: Mapped[int | None] = mapped_column(Integer)
    times_local: Mapped[list | None] = mapped_column(JSON)
    timezone: Mapped[str | None] = mapped_column(String(80))
    start_date: Mapped[date | None] = mapped_column(Date)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    administration_notes: Mapped[str | None] = mapped_column(String(500))
    examination_details: Mapped[str | None] = mapped_column(String(1000))
    indication: Mapped[str | None] = mapped_column(String(1000))
    contraindications: Mapped[str | None] = mapped_column(String(1000))
    rationale: Mapped[str | None] = mapped_column(String(1500))
    source_reference: Mapped[str | None] = mapped_column(String(500))
    approved_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))


class ClinicalOrderAudit(IdMixin, TimestampMixin, Base):
    __tablename__ = "clinical_order_audit"
    order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clinical_orders.id"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSON, nullable=False)
