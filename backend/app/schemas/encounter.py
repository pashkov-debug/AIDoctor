from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FunctionalImpact = Literal[
    "none",
    "mild",
    "moderate",
    "severe",
]


class EncounterCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        min_length=1,
        max_length=50,
    )

    complaints: list[str] = Field(
        default_factory=list,
        max_length=50,
    )

    functional_impact: FunctionalImpact | None = None

    clinician_question: str | None = Field(
        default=None,
        max_length=2000,
    )

    occurred_at: datetime | None = None


class EncounterRead(BaseModel):
    id: str
    patient_id: str
    occurred_at: datetime
    reason: str
    status: str

    complaints: list[str]
    functional_impact: FunctionalImpact | None
    clinician_question: str | None

    created_at: datetime


class EncounterListResponse(BaseModel):
    items: list[EncounterRead]
    total: int
