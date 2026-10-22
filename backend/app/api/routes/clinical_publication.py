"""Права проверяются до обращения к клиническому сервису; пациент не принимает решения."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.access import require_patient
from app.db.session import get_db
from app.models.access import User
from app.models.patient import Patient
from app.schemas.clinical_publication import (
    ClinicalPublicationRead,
    PatientPublicationsList,
    PublishRequest,
    RevokeRequest,
)
from app.services import clinical_publication as service

router = APIRouter(tags=["clinical-publication"])
DB = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(current_user)]


def require_clinician(db: Session, actor: User, patient_id: str) -> None:
    if actor.role != "doctor":
        raise HTTPException(403, detail="Требуется роль врача")
    if (
        db.scalar(select(Patient.id).where(Patient.id == patient_id, Patient.deleted_at.is_(None)))
        is None
    ):
        raise HTTPException(404, detail="Пациент не найден")
    require_patient(db, actor, patient_id)


@router.get("/patients/me/clinical-publications", response_model=PatientPublicationsList)
def my_publications(db: DB, actor: Actor):
    if actor.role != "patient":
        raise HTTPException(403, detail="Требуется роль пациента")
    return service.list_for_patient(db, actor.id)


@router.get(
    "/patients/{patient_id}/clinical-publications",
    response_model=list[ClinicalPublicationRead],
)
def list_publications(patient_id: str, db: DB, actor: Actor):
    require_clinician(db, actor, patient_id)
    return service.list_for_doctor(db, patient_id)


@router.post(
    "/patients/{patient_id}/history-events/{event_id}/confirm",
    response_model=ClinicalPublicationRead,
    status_code=201,
)
def confirm_event(patient_id: str, event_id: str, db: DB, actor: Actor):
    require_clinician(db, actor, patient_id)
    return service.confirm(db, patient_id, event_id, actor.id)


@router.post(
    "/patients/{patient_id}/clinical-publications/{record_id}/publish",
    response_model=ClinicalPublicationRead,
)
def publish_event(patient_id: str, record_id: str, payload: PublishRequest, db: DB, actor: Actor):
    require_clinician(db, actor, patient_id)
    return service.publish(db, patient_id, record_id, actor.id, payload)


@router.post(
    "/patients/{patient_id}/clinical-publications/{record_id}/revoke",
    response_model=ClinicalPublicationRead,
)
def revoke_event(patient_id: str, record_id: str, payload: RevokeRequest, db: DB, actor: Actor):
    require_clinician(db, actor, patient_id)
    return service.revoke(db, patient_id, record_id, actor.id, payload)
