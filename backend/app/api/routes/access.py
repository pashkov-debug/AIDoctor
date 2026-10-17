from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.db.session import get_db
from app.models.access import DoctorPatient, User
from app.models.patient import Patient

router = APIRouter(tags=["access"])


class LinkPayload(BaseModel):
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
    if doctor is None or doctor.role != "doctor" or patient is None:
        raise HTTPException(status_code=404, detail="Doctor/patient not found")
    existing = db.scalar(
        select(DoctorPatient).where(
            DoctorPatient.doctor_id == doctor.id, DoctorPatient.patient_id == patient.id
        )
    )
    if existing:
        return {"id": existing.id}
    record = DoctorPatient(doctor_id=doctor.id, patient_id=patient.id)
    db.add(record)
    db.commit()
    return {"id": record.id}


class PatientAccountPayload(BaseModel):
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
    target = db.get(Patient, payload.patient_id)
    account = db.get(User, payload.user_id)
    if target is None or account is None or account.role != "patient":
        raise HTTPException(status_code=404, detail="Account/patient not found")
    if db.scalar(select(Patient.id).where(Patient.user_id == account.id, Patient.id != target.id)):
        raise HTTPException(status_code=409, detail="Account already linked")
    target.user_id = account.id
    db.commit()
    return {"patient_id": target.id, "user_id": account.id}
