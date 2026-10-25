"""Ввод и просмотр клинических фактов; единая транзакция с аудитом."""

from app.db.base import utc_now
from app.models.clinical_entry_audit import ClinicalEntryAudit
from app.models.encounter import Encounter
from app.models.history_event import HistoryEvent
from app.models.medical_record import MedicalObservation
from app.schemas.clinical_entry import (
    ManualHistoryCreate,
    ManualObservationCreate,
    ObservationList,
    ObservationRead,
)
from app.schemas.history_event import HistoryEventRead
from app.services.history_event import HistoryEventService
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def _encounter(db: Session, patient_id: str, encounter_id: str | None) -> None:
    if encounter_id is None:
        return
    exists = db.scalar(
        select(Encounter.id).where(
            Encounter.id == encounter_id,
            Encounter.patient_id == patient_id,
        )
    )
    if exists is None:
        raise HTTPException(status_code=422, detail="Визит не принадлежит пациенту")


def _save_with_audit(
    db: Session,
    row: HistoryEvent | MedicalObservation,
    *,
    patient_id: str,
    doctor_id: str,
    record_type: str,
    details: dict,
) -> None:
    db.add(row)
    try:
        db.flush()
        db.add(
            ClinicalEntryAudit(
                patient_id=patient_id,
                actor_id=doctor_id,
                record_type=record_type,
                record_id=row.id,
                action="created",
                source_ref=f"doctor:{doctor_id}",
                details_json=details,
            )
        )
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        raise


def create_history(
    db: Session,
    patient_id: str,
    doctor_id: str,
    payload: ManualHistoryCreate,
) -> HistoryEventRead:
    encounter_id = str(payload.encounter_id) if payload.encounter_id else None
    _encounter(db, patient_id, encounter_id)
    row = HistoryEvent(
        patient_id=patient_id,
        encounter_id=encounter_id,
        category=payload.category,
        fact_json=payload.fact,
        occurred_at=payload.occurred_at or utc_now(),
        priority=payload.priority,
        source_ref=f"doctor:{doctor_id}",
    )
    _save_with_audit(
        db,
        row,
        patient_id=patient_id,
        doctor_id=doctor_id,
        record_type="history_event",
        details={"category": payload.category, "encounter_id": encounter_id},
    )
    return HistoryEventService._to_read_model(row)


def _observation_read(row: MedicalObservation) -> ObservationRead:
    return ObservationRead(
        id=row.id,
        patient_id=row.patient_id,
        encounter_id=row.encounter_id,
        code_system=row.code_system,
        code=row.code,
        observed_at=row.observed_at,
        value=row.value_json,
        source_ref=row.source_ref,
        supersedes_id=row.supersedes_id,
        created_at=row.created_at,
    )


def create_observation(
    db: Session,
    patient_id: str,
    doctor_id: str,
    payload: ManualObservationCreate,
) -> ObservationRead:
    encounter_id = str(payload.encounter_id) if payload.encounter_id else None
    _encounter(db, patient_id, encounter_id)
    row = MedicalObservation(
        patient_id=patient_id,
        encounter_id=encounter_id,
        code_system=payload.code_system,
        code=payload.code,
        observed_at=payload.observed_at or utc_now(),
        value_json=payload.value,
        source_ref=f"doctor:{doctor_id}",
    )
    _save_with_audit(
        db,
        row,
        patient_id=patient_id,
        doctor_id=doctor_id,
        record_type="medical_observation",
        details={"code": payload.code, "encounter_id": encounter_id},
    )
    return _observation_read(row)


def list_observations(db: Session, patient_id: str) -> ObservationList:
    rows = db.scalars(
        select(MedicalObservation)
        .where(MedicalObservation.patient_id == patient_id)
        .order_by(MedicalObservation.observed_at.desc(), MedicalObservation.id.desc())
        .limit(500)
    ).all()
    total = (
        db.scalar(
            select(func.count(MedicalObservation.id)).where(
                MedicalObservation.patient_id == patient_id
            )
        )
        or 0
    )
    return ObservationList(items=[_observation_read(x) for x in rows], total=total)
