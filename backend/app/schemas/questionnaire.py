from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class QuestionnaireResponseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scale_id: str = Field(
        min_length=1,
        max_length=50,
    )

    item_scores: list[int] = Field(
        min_length=1,
        max_length=100,
    )

    measured_at: datetime | None = None


class QuestionnaireResponseRead(BaseModel):
    id: str

    patient_id: str
    encounter_id: str

    scale_id: str

    item_scores: list[int]
    total_score: int

    measured_at: datetime
    created_at: datetime


class QuestionnaireResponseList(BaseModel):
    items: list[QuestionnaireResponseRead]
    total: int
