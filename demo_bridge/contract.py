"""Публичный JSON-контракт без вывода реальных идентификаторов/других пациентов."""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.patient import Patient
from app.services.context_builder import ClinicalContext, ContextBuilder

SCHEMA_VERSION = "1.0"
PUBLIC_ID = "DEMO-001"
PATIENT_ID = "00000000-0000-4000-8000-000000000001"
ENCOUNTER_ID = "00000000-0000-4000-8000-000000000002"
HISTORY_ID = "00000000-0000-4000-8000-000000000003"
HISTORY_SECOND_ID = "00000000-0000-4000-8000-000000000004"
OBSERVATION_ID = "00000000-0000-4000-8000-000000000005"

ALLOWED_FACTS = {
    ("encounter", ENCOUNTER_ID),
    ("history_event", HISTORY_ID),
    ("history_event", HISTORY_SECOND_ID),
    ("observation", OBSERVATION_ID),
}


class DemoPatientData(BaseModel):
    demo_id: Literal["DEMO-001"]
    synthetic: Literal[True]
    sex: Literal["female"]
    age_years: Literal[35]
    diagnosis_established: Literal[False]
    label: str


class DemoContextData(BaseModel):
    demo_id: Literal["DEMO-001"]
    synthetic: Literal[True]
    clinical_context: ClinicalContext
    notices: list[str]


class DemoEnvelope(BaseModel):
    schema_version: Literal["1.0"]
    synthetic: Literal[True]
    mode: Literal["synthetic_demo_only"]
    source: Literal["aidoctor_context_builder_demo_db"]
    clinical_processing_allowed: Literal[False]
    data: DemoPatientData
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DemoContextEnvelope(DemoEnvelope):
    data: DemoContextData


class DemoDataError(RuntimeError):
    """Источник не удовлетворяет требованиям только синтетических данных."""


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_data(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def envelope(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "synthetic": True,
        "mode": "synthetic_demo_only",
        "source": "aidoctor_context_builder_demo_db",
        "clinical_processing_allowed": False,
        "data": data,
        "content_sha256": sha256_data(data),
    }


def read_verified_case(session: Session) -> tuple[Patient, ClinicalContext]:
    if session.scalar(select(func.count(Patient.id))) != 1:
        raise DemoDataError("В демонстрационной БД ожидается ровно один пациент")
    patient = session.get(Patient, PATIENT_ID)
    if patient is None or patient.deleted_at is not None or patient.alias != PUBLIC_ID:
        raise DemoDataError("Демонстрационный пациент отсутствует либо изменён")

    demographics = patient.demographics_json
    if (
        not isinstance(demographics, dict)
        or set(demographics) != {"synthetic", "sex", "age_years"}
        or demographics["synthetic"] is not True
        or demographics["sex"] != "female"
        or demographics["age_years"] != 35
    ):
        raise DemoDataError("У пациента отсутствует допустимая синтетическая метка")

    context = ContextBuilder(session).build(PATIENT_ID)
    if (
        context.patient_id != PATIENT_ID
        or context.schema_version != SCHEMA_VERSION
        or context.truncated_sources
        or context.excluded_attachments_count != 0
        or {(fact.kind, fact.record_id) for fact in context.items} != ALLOWED_FACTS
        or len(context.items) != len(ALLOWED_FACTS)
    ):
        raise DemoDataError("Контекст изменён или содержит недопустимые источники")

    for fact in context.items:
        payload = fact.payload
        if fact.kind == "encounter":
            synthetic = isinstance(payload.get("details"), dict) and (
                payload["details"].get("synthetic") is True
            )
        elif fact.kind == "history_event":
            synthetic = isinstance(payload.get("fact"), dict) and (
                payload["fact"].get("synthetic") is True
            )
        else:
            synthetic = isinstance(payload.get("value"), dict) and (
                payload["value"].get("synthetic") is True
            )
        if not synthetic:
            raise DemoDataError("Контекст содержит факт без синтетической метки")

    content = {
        "schema_version": context.schema_version,
        "patient_id": context.patient_id,
        "items": [
            item.model_dump(mode="json", exclude_none=False) for item in context.items
        ],
        "truncated_sources": context.truncated_sources,
        "excluded_attachments_count": context.excluded_attachments_count,
    }
    if sha256_data(content) != context.content_sha256:
        raise DemoDataError("Неверный SHA-256 Context Builder")
    return patient, context


def patient_response(session: Session) -> dict[str, Any]:
    patient, _ = read_verified_case(session)
    return envelope(
        {
            "demo_id": PUBLIC_ID,
            "synthetic": True,
            "sex": patient.demographics_json["sex"],
            "age_years": patient.demographics_json["age_years"],
            "diagnosis_established": False,
            "label": "Вымышленный пациент (AIDoctor Demo)",
        }
    )


def context_response(session: Session) -> dict[str, Any]:
    _, context = read_verified_case(session)
    return envelope(
        {
            "demo_id": PUBLIC_ID,
            "synthetic": True,
            "clinical_context": context.model_dump(mode="json", exclude_none=False),
            "notices": [
                "Все сведения вымышлены и существуют только в отдельной базе aidoctor_demo.",
                "Вложения и автоматический клинический допуск отсутствуют.",
                "Диагностические выводы модели требуют проверки врача.",
            ],
        }
    )
