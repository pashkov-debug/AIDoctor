"""Технические идентификаторы follow-up без медицинских подробностей."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SafetyFollowupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    alert_id: str
    created_at: datetime
