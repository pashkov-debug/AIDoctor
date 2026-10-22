"""Профиль и клинические предпочтения только текущего врача."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.db.session import get_db
from app.models.access import User
from app.schemas.doctor_settings import (
    ClinicalUpdate,
    DoctorContextRead,
    DoctorSettingsRead,
    ProfileUpdate,
)
from app.services.doctor_settings import read_doctor_context, read_settings, update_settings

router = APIRouter(prefix="/doctors/me", tags=["doctor-settings"])
UserDep = Annotated[User, Depends(current_user)]
DBDep = Annotated[Session, Depends(get_db)]


def require_current_doctor(user: UserDep) -> User:
    if user.role != "doctor":
        raise HTTPException(status_code=403, detail="Doctor role required")
    return user


DoctorDep = Annotated[User, Depends(require_current_doctor)]


@router.get("/settings", response_model=DoctorSettingsRead)
def get_settings(doctor: DoctorDep, db: DBDep) -> DoctorSettingsRead:
    return read_settings(db, doctor.id)


@router.put("/settings/profile", response_model=DoctorSettingsRead)
def put_profile(payload: ProfileUpdate, doctor: DoctorDep, db: DBDep) -> DoctorSettingsRead:
    return update_settings(
        db,
        doctor,
        section="profile",
        expected_version=payload.expected_version,
        values=payload.model_dump(exclude={"expected_version"}),
    )


@router.put("/settings/clinical", response_model=DoctorSettingsRead)
def put_clinical(payload: ClinicalUpdate, doctor: DoctorDep, db: DBDep) -> DoctorSettingsRead:
    return update_settings(
        db,
        doctor,
        section="clinical",
        expected_version=payload.expected_version,
        values=payload.model_dump(exclude={"expected_version"}),
    )


@router.get("/doctor-context", response_model=DoctorContextRead)
def get_doctor_context(doctor: DoctorDep, db: DBDep) -> DoctorContextRead:
    return read_doctor_context(db, doctor.id)
