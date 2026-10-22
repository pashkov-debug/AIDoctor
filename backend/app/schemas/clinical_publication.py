"""Строгий контракт подтверждения и публикации клинических событий UI-2C."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    patient_text: str = Field(min_length=1, max_length=2000)
    confirm_patient_visibility: Literal[True]


class RevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


class ClinicalPublicationRead(BaseModel):
    id: str
    patient_id: str
    history_event_id: str
    status: Literal["confirmed", "published", "revoked"]
    version: int
    confirmed_by_id: str
    confirmed_at: datetime
    patient_text: str | None
    published_at: datetime | None
    revoked_at: datetime | None
    revoke_reason: str | None


class PatientPublicationRead(BaseModel):
    id: str
    text: str
    published_at: datetime


class PatientPublicationsList(BaseModel):
    items: list[PatientPublicationRead]
    total: int
