"""Контракт inbox: без медицинских текстов и контактных данных."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SafetyInAppNotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    patient_id: str
    alert_id: str
    created_at: datetime
