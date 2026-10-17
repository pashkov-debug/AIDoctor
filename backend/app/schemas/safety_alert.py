"""Контракт API: ручной сигнал не является автоматическим медицинским диагнозом."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ReasonCode = Literal["clinician_review", "care_coordination", "urgent_attention"]
Priority = Literal["standard", "urgent"]
AlertStatus = Literal["open", "acknowledged"]


class SafetyAlertCreate(BaseModel):
    reason_code: ReasonCode
    priority: Priority


class SafetyAlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    created_at: datetime
    created_by_id: str
    reason_code: ReasonCode
    priority: Priority
    status: AlertStatus
    acknowledged_at: datetime | None
    acknowledged_by_id: str | None
    delivery_status: Literal["not_configured"] = "not_configured"
