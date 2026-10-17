"""Чтение фактов для подготовки контекста; без вызовов LLM и записи в БД."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from app.models.encounter import Encounter
from app.models.history_event import HistoryEvent
from app.models.medical_record import MedicalAttachment, MedicalObservation
from app.models.patient import Patient
from app.models.questionnaire_response import QuestionnaireResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

MAX_ITEMS_PER_SOURCE = 100
CONTEXT_VERSION = "1.0"


class ContextFact(BaseModel):
    kind: Literal["encounter", "history_event", "observation", "questionnaire"]
    record_id: str
    at: datetime
    source_ref: str
    payload: dict[str, Any]


class ClinicalContext(BaseModel):
    schema_version: Literal["1.0"] = CONTEXT_VERSION
    patient_id: str
    generated_at: datetime
    items: list[ContextFact]
    truncated_sources: list[str] = Field(default_factory=list)
    excluded_attachments_count: int
    content_sha256: str


class ContextPatientNotFoundError(LookupError):
    pass


class ContextBuilder:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _read_limited(self, statement: Any) -> tuple[list[Any], bool]:
        results = list(
            self._session.scalars(statement.limit(MAX_ITEMS_PER_SOURCE + 1)).all()
        )
        return results[:MAX_ITEMS_PER_SOURCE], len(results) > MAX_ITEMS_PER_SOURCE

    def build(self, patient_id: str) -> ClinicalContext:
        # Права доступа проверяет вызывающий API до обращения к этому сервису.
        exists = self._session.scalar(
            select(Patient.id).where(
                Patient.id == patient_id,
                Patient.deleted_at.is_(None),
            )
        )
        if exists is None:
            raise ContextPatientNotFoundError(patient_id)

        cutoff = datetime.now(UTC)
        items: list[ContextFact] = []
        truncated_sources: list[str] = []

        encounters, truncated = self._read_limited(
            select(Encounter)
            .where(
                Encounter.patient_id == patient_id,
                Encounter.created_at <= cutoff,
            )
            .order_by(Encounter.occurred_at.desc(), Encounter.id)
        )
        if truncated:
            truncated_sources.append("encounters")
        items.extend(
            ContextFact(
                kind="encounter",
                record_id=value.id,
                at=value.occurred_at,
                source_ref=f"encounter:{value.id}",
                payload={
                    "reason": value.reason,
                    "status": value.status,
                    "details": value.payload_json,
                },
            )
            for value in encounters
        )

        # Коррекции вытесняют прежние факты даже при цепочках исправлений.
        replaced_events = select(HistoryEvent.supersedes_id).where(
            HistoryEvent.patient_id == patient_id,
            HistoryEvent.supersedes_id.is_not(None),
            HistoryEvent.created_at <= cutoff,
        )
        events, truncated = self._read_limited(
            select(HistoryEvent)
            .where(
                HistoryEvent.patient_id == patient_id,
                HistoryEvent.created_at <= cutoff,
                HistoryEvent.id.not_in(replaced_events),
            )
            .order_by(HistoryEvent.occurred_at.desc(), HistoryEvent.id)
        )
        if truncated:
            truncated_sources.append("history_events")
        items.extend(
            ContextFact(
                kind="history_event",
                record_id=value.id,
                at=value.occurred_at,
                source_ref=value.source_ref,
                payload={
                    "category": value.category,
                    "priority": value.priority,
                    "fact": value.fact_json,
                    "correction_reason": value.correction_reason,
                },
            )
            for value in events
        )

        replaced_observations = select(MedicalObservation.supersedes_id).where(
            MedicalObservation.patient_id == patient_id,
            MedicalObservation.supersedes_id.is_not(None),
            MedicalObservation.created_at <= cutoff,
        )
        observations, truncated = self._read_limited(
            select(MedicalObservation)
            .where(
                MedicalObservation.patient_id == patient_id,
                MedicalObservation.created_at <= cutoff,
                MedicalObservation.id.not_in(replaced_observations),
            )
            .order_by(MedicalObservation.observed_at.desc(), MedicalObservation.id)
        )
        if truncated:
            truncated_sources.append("observations")
        items.extend(
            ContextFact(
                kind="observation",
                record_id=value.id,
                at=value.observed_at,
                source_ref=value.source_ref or f"observation:{value.id}",
                payload={
                    "code_system": value.code_system,
                    "code": value.code,
                    "value": value.value_json,
                },
            )
            for value in observations
        )

        questionnaires, truncated = self._read_limited(
            select(QuestionnaireResponse)
            .where(
                QuestionnaireResponse.patient_id == patient_id,
                QuestionnaireResponse.created_at <= cutoff,
            )
            .order_by(QuestionnaireResponse.measured_at.desc(), QuestionnaireResponse.id)
        )
        if truncated:
            truncated_sources.append("questionnaires")
        items.extend(
            ContextFact(
                kind="questionnaire",
                record_id=value.id,
                at=value.measured_at,
                source_ref=f"questionnaire_response:{value.id}",
                payload={
                    "encounter_id": value.encounter_id,
                    "scale_id": value.scale_id,
                    "total_score": value.total_score,
                    "item_scores": value.item_scores_json,
                },
            )
            for value in questionnaires
        )

        # Пока нет AV/CDR и верификации извлечения, любые файлы исключены.
        excluded = self._session.scalar(
            select(func.count(MedicalAttachment.id)).where(
                MedicalAttachment.patient_id == patient_id
            )
        )
        items.sort(
            key=lambda item: (
                item.at.isoformat(),
                item.kind,
                item.record_id,
            )
        )
        serialized = [
            item.model_dump(mode="json", exclude_none=False) for item in items
        ]
        canonical = json.dumps(
            {
                "schema_version": CONTEXT_VERSION,
                "patient_id": patient_id,
                "items": serialized,
                "truncated_sources": truncated_sources,
                "excluded_attachments_count": excluded or 0,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return ClinicalContext(
            patient_id=patient_id,
            generated_at=cutoff,
            items=items,
            truncated_sources=truncated_sources,
            excluded_attachments_count=excluded or 0,
            content_sha256=hashlib.sha256(canonical).hexdigest(),
        )
