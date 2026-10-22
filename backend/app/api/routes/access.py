"""Существующие административные операции связей (совместимость UI-1B)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.db.session import get_db
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from app.services.admin_audit import record_admin_action

router = APIRouter(tags=["access"])


class LinkPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    doctor_id: str
    patient_id: str


@router.post("/access/link", status_code=201)
def link_patient(
    payload: LinkPayload,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    doctor = db.get(User, payload.doctor_id)
    patient = db.get(Patient, payload.patient_id)
    if (
        doctor is None
        or doctor.role != "doctor"
        or patient is None
        or patient.deleted_at is not None
    ):
        raise HTTPException(status_code=404, detail="Doctor/patient not found")
    existing = db.scalar(
        select(DoctorPatient).where(
            DoctorPatient.doctor_id == doctor.id,
            DoctorPatient.patient_id == patient.id,
        )
    )
    if existing:
        return {"id": existing.id}
    record = DoctorPatient(doctor_id=doctor.id, patient_id=patient.id)
    try:
        db.add(record)
        db.flush()
        record_admin_action(
            db,
            actor_id=user.id,
            action="doctor_patient_linked",
            target_id=record.id,
            details={"doctor_id": doctor.id, "patient_id": patient.id},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Повторный конкурентный запрос не должен создавать вторую связь.
        existing = db.scalar(
            select(DoctorPatient).where(
                DoctorPatient.doctor_id == doctor.id,
                DoctorPatient.patient_id == patient.id,
            )
        )
        if existing is not None:
            return {"id": existing.id}
        raise HTTPException(status_code=409, detail="Конфликт создания связи") from exc
    return {"id": record.id}


class PatientAccountPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_id: str
    user_id: str


@router.post("/access/patient-account")
def bind_patient_user(
    payload: PatientAccountPayload,
    user: Annotated[User, Depends(current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin required")
    # Блокировка карточки защищает от параллельной смены user_id.
    target = db.scalar(select(Patient).where(Patient.id == payload.patient_id).with_for_update())
    account = db.get(User, payload.user_id)
    if (
        target is None
        or target.deleted_at is not None
        or account is None
        or account.role != "patient"
    ):
        raise HTTPException(status_code=404, detail="Account/patient not found")
    if target.user_id is not None:
        if target.user_id == account.id:
            return {"patient_id": target.id, "user_id": account.id}
        raise HTTPException(status_code=409, detail="Карточка уже привязана")
    existing = db.scalar(
        select(Patient.id).where(Patient.user_id == account.id, Patient.id != target.id)
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="Account already linked")
    try:
        target.user_id = account.id
        record_admin_action(
            db,
            actor_id=user.id,
            action="patient_account_bound",
            target_id=target.id,
            details={"user_id": account.id},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Account already linked") from exc
    return {"patient_id": target.id, "user_id": account.id}
