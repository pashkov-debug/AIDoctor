"""Минимальные типизированные административные контракты UI-1C."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CreateAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=256)
    role: Literal["doctor", "patient"]

    @field_validator("username")
    @classmethod
    def username_trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("Пробелы по краям логина запрещены")
        return value


class AccountRead(BaseModel):
    id: str
    username: str
    role: Literal["admin", "doctor", "patient"]
    created_at: datetime


class CreateSyntheticPatient(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alias: str = Field(min_length=1, max_length=100)

    @field_validator("alias")
    @classmethod
    def trim_alias(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Псевдоним пуст")
        return value


class AdminPatientRead(BaseModel):
    id: str
    alias: str
    synthetic: bool
    user_id: str | None


class AccessLinkRead(BaseModel):
    id: str
    doctor_id: str
    patient_id: str
    created_at: datetime


class AdminAuditRead(BaseModel):
    id: str
    actor_id: str
    action: str
    target_id: str
    created_at: datetime
    details: dict
