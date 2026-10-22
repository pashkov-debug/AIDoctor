"""Строгие контракты UI-3A. Черновик и опубликованное назначение раздельны."""

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Kind = Literal["medication", "examination"]
Status = Literal["draft", "approved", "cancelled"]


class OrderDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: UUID
    kind: Kind
    name: str = Field(min_length=1, max_length=200)
    active_ingredient: str | None = Field(default=None, max_length=200)
    dosage_form: str | None = Field(default=None, max_length=120)
    strength: str | None = Field(default=None, max_length=120)
    dose_value: Decimal | None = Field(
        default=None, gt=0, le=999999, max_digits=12, decimal_places=4
    )
    dose_unit: str | None = Field(default=None, max_length=60)
    route: str | None = Field(default=None, max_length=120)
    frequency_per_day: int | None = Field(default=None, ge=1, le=12)
    times_local: list[str] | None = Field(default=None, min_length=1, max_length=12)
    timezone: str | None = Field(default=None, max_length=80)
    start_date: date | None = None
    duration_days: int | None = Field(default=None, ge=1, le=3650)
    administration_notes: str | None = Field(default=None, max_length=500)
    examination_details: str | None = Field(default=None, max_length=1000)
    indication: str | None = Field(default=None, max_length=1000)
    contraindications: str | None = Field(default=None, max_length=1000)
    rationale: str | None = Field(default=None, max_length=1500)
    source_reference: str | None = Field(default=None, max_length=500)

    @field_validator("times_local")
    @classmethod
    def valid_times(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", x) for x in value):
            raise ValueError("Время приёма должно иметь формат ЧЧ:ММ")
        if len(set(value)) != len(value):
            raise ValueError("Время приёма не должно повторяться")
        return sorted(value)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str | None) -> str | None:
        if not value:
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            # Python под Windows может не иметь системной базы IANA.
            if value not in {"UTC", "Europe/Moscow", "Europe/Warsaw"}:
                raise ValueError("Неизвестный пояс IANA (нужна база tzdata)") from exc
        except ValueError as exc:
            raise ValueError("Некорректный пояс IANA") from exc
        return value

    @model_validator(mode="after")
    def kind_fields(self):
        medication_fields = (
            "active_ingredient",
            "dosage_form",
            "strength",
            "dose_value",
            "dose_unit",
            "route",
            "frequency_per_day",
            "times_local",
            "timezone",
            "duration_days",
            "administration_notes",
            "contraindications",
        )
        if self.kind == "examination" and any(
            getattr(self, key) is not None for key in medication_fields
        ):
            raise ValueError("Поля препарата недопустимы для обследования")
        if self.kind == "medication" and self.examination_details is not None:
            raise ValueError("Поле обследования недопустимо для препарата")
        return self


class OrderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    data: OrderDraftCreate


class OrderApprove(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    confirm_patient_visibility: Literal[True]
    confirm_clinical_review: Literal[True]


class OrderCancel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


class OrderRead(OrderDraftCreate):
    id: str
    patient_id: str
    author_id: str
    status: Status
    version: int
    created_at: datetime
    approved_at: datetime | None
    approved_by_id: str | None
    cancelled_at: datetime | None
    cancel_reason: str | None


class PatientOrderRead(BaseModel):
    """Пациент не получает внутренние обоснования, версии и идентификаторы врачей."""

    id: str
    kind: Kind
    name: str
    active_ingredient: str | None
    dosage_form: str | None
    strength: str | None
    dose_value: Decimal | None
    dose_unit: str | None
    route: str | None
    frequency_per_day: int | None
    times_local: list[str] | None
    timezone: str | None
    start_date: date | None
    duration_days: int | None
    administration_notes: str | None
    examination_details: str | None
    approved_at: datetime


class PatientOrdersList(BaseModel):
    items: list[PatientOrderRead]
    total: int
