from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.access import User, DoctorPatient
from app.models.encounter import Encounter
from app.models.patient import Patient

def can_access_patient(session: Session, user: User, patient_id: str) -> bool:
    if user.role == "admin":
        return True
    if user.role == "doctor":
        return session.scalar(select(DoctorPatient.id).where(
            DoctorPatient.doctor_id == user.id, DoctorPatient.patient_id == patient_id)) is not None
    return user.role == "patient" and session.scalar(select(Patient.id).where(
        Patient.id == patient_id, Patient.user_id == user.id)) is not None

def require_patient(session: Session, user: User, patient_id: str) -> None:
    if not can_access_patient(session, user, patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")

def require_doctor(user: User) -> None:
    if user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Doctor role required")

def require_encounter(session: Session, user: User, encounter_id: str) -> None:
    patient_id = session.scalar(select(Encounter.patient_id).where(Encounter.id == encounter_id))
    if patient_id is None:
        raise HTTPException(status_code=404, detail="Encounter not found")
    require_patient(session, user, patient_id)
