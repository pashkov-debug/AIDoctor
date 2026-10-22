"""Минимальная публичная для самого пациента проекция его карточки.

Полные медицинские события, demographics_json, AI-черновики и внутренние
заметки врача не входят в этот контракт.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PatientPortalRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["patient_portal.v1"] = "patient_portal.v1"
    patient_id: str
    alias: str
    created_at: datetime
