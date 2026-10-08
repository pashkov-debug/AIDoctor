from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PatientCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alias: str = Field(
        min_length=1,
        max_length=100,
    )

    demographics: dict[str, Any] = Field(
        default_factory=dict,
    )


class PatientRead(BaseModel):
    id: str
    alias: str
    demographics: dict[str, Any]
    created_at: datetime


class PatientListResponse(BaseModel):
    items: list[PatientRead]
    total: int
