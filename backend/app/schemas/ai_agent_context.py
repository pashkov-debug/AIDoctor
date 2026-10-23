"""Версионированный контекст для БУДУЩЕЙ проверки лекарственных проектов AI.

Этот контракт сам по себе не разрешает передачу данных внешнему сервису.
"""

from datetime import datetime
from typing import Any, Literal

from app.services.context_builder import ClinicalContext
from pydantic import BaseModel, ConfigDict, Field


class OrderReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: int = Field(ge=1)
    status: Literal["draft", "approved"]
    kind: Literal["medication", "examination"]
    name: str
    active_ingredient: str | None
    dosage_form: str | None
    strength: str | None
    dose_value: str | None
    dose_unit: str | None
    route: str | None
    frequency_per_day: int | None
    times_local: list[str] | None
    timezone: str | None
    start_date: str | None
    duration_days: int | None
    administration_notes: str | None
    examination_details: str | None
    indication: str | None
    contraindications: str | None
    rationale: str | None
    source_reference: str | None


class OrdersReviewSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["orders_for_ai_review.v1"] = "orders_for_ai_review.v1"
    approved_orders: list[OrderReviewItem]
    proposed_orders_for_review: list[OrderReviewItem]
    draft_orders_are_not_treatment: Literal[True] = True
    clinical_safety_validated: Literal[False] = False


class AIAgentContextRead(BaseModel):
    """Пакет для ручной инспекции, не автоматической отправки провайдеру."""

    schema_version: Literal["ai_agent_context.v1"] = "ai_agent_context.v1"
    request_id: str
    patient_id: str
    doctor_id: str
    question: str
    created_at: datetime
    patient_context: ClinicalContext
    doctor_context: dict[str, Any]
    orders_review: OrdersReviewSnapshot
    orders_sha256: str
    excluded_attachments: list[dict[str, Any]]
    llm_dispatch_enabled: Literal[False] = False
