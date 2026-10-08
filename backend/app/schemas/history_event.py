from datetime import datetime
from typing import Any

from pydantic import BaseModel


class HistoryEventRead(BaseModel):
    id: str

    patient_id: str
    encounter_id: str | None

    category: str
    fact: dict[str, Any]

    occurred_at: datetime
    priority: str

    source_ref: str

    supersedes_id: str | None
    correction_reason: str | None

    created_at: datetime


class HistoryEventList(BaseModel):
    items: list[HistoryEventRead]
    total: int
