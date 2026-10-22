"""Строгие входные и выходные контракты UI-1."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileFields(StrictModel):
    full_name: str | None = Field(default=None, max_length=160)
    specialty: str | None = Field(default=None, max_length=120)
    institution: str | None = Field(default=None, max_length=200)
    professional_info: str | None = Field(default=None, max_length=2000)
    contact_email: str | None = Field(default=None, max_length=254)

    @field_validator("*", mode="before")
    @classmethod
    def normalize_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("contact_email")
    @classmethod
    def validate_contact(cls, value: str | None) -> str | None:
        if value is not None and (
            value.count("@") != 1
            or any(ch.isspace() for ch in value)
            or not value.split("@")[0]
            or "." not in value.split("@")[1]
        ):
            raise ValueError("Укажите корректный контактный email")
        return value


class ClinicalFields(StrictModel):
    practice_country: str | None = Field(default=None, max_length=120)
    rki_mode: Literal["disabled", "consider_if_verified"] = "disabled"
    institution_type: str | None = Field(default=None, max_length=120)
    clinical_specialty: str | None = Field(default=None, max_length=120)

    @field_validator("practice_country", "institution_type", "clinical_specialty", mode="before")
    @classmethod
    def normalize_strings(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip() or None
        return value


class ProfileUpdate(ProfileFields):
    expected_version: int = Field(ge=0)


class ClinicalUpdate(ClinicalFields):
    expected_version: int = Field(ge=0)


class DoctorSettingsRead(StrictModel):
    schema_version: Literal["doctor_settings.v1"] = "doctor_settings.v1"
    version: int
    profile: ProfileFields
    clinical: ClinicalFields


class RussianGuidelinesContext(StrictModel):
    scope: Literal["russian_clinical_guidelines_approved_by_minzdrav"] = (
        "russian_clinical_guidelines_approved_by_minzdrav"
    )
    mode: Literal["disabled", "consider_if_verified"]
    source_verification: Literal["required"] = "required"


class DoctorContextRead(StrictModel):
    schema_version: Literal["doctor_context.v1"] = "doctor_context.v1"
    doctor_id: str
    profile_version: int
    country: str | None
    rki: RussianGuidelinesContext
    institution_type: str | None
    specialty: str | None
