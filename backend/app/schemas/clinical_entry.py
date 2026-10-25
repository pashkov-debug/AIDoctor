"""Строгие поля ручного ввода; медицинские решения не формируются AI."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

MAX_FACT_BYTES = 16384


def _validated_json(value: dict[str, Any]) -> dict[str, Any]:
    if len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")) > MAX_FACT_BYTES:
        raise ValueError("Клиническая запись превышает 16 КиБ")
    return value


class ManualHistoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    encounter_id: UUID | None = None
    category: str = Field(min_length=1, max_length=50)
    fact: dict[str, Any] = Field(min_length=1)
    occurred_at: AwareDatetime | None = None
    priority: str = Field(default="normal", min_length=1, max_length=20)

    @field_validator("fact")
    @classmethod
    def valid_fact(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validated_json(value)


class ManualObservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    encounter_id: UUID | None = None
    code_system: str | None = Field(default=None, max_length=100)
    code: str = Field(min_length=1, max_length=120)
    observed_at: AwareDatetime | None = None
    value: dict[str, Any] = Field(min_length=1)

    @field_validator("value")
    @classmethod
    def valid_value(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validated_json(value)


class ObservationRead(BaseModel):
    id: str
    patient_id: str
    encounter_id: str | None
    code_system: str | None
    code: str
    observed_at: datetime
    value: dict[str, Any]
    source_ref: str | None
    supersedes_id: str | None
    created_at: datetime


class ObservationList(BaseModel):
    items: list[ObservationRead]
    total: int
