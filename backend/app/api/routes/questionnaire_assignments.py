"""Учебные опросники: каталог, назначения врача, ответы своего пациента."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.access import require_patient
from app.db.session import get_db
from app.models.access import User
from app.models.patient import Patient
from app.schemas.questionnaire_assignment import (
    AssignDemoTest,
    CancelDemoTest,
    DoctorTestAssignmentRead,
    SubmitDemoTest,
    TestAssignmentRead,
    TestCatalogEntry,
)
from app.services import questionnaire_assignment as service

router = APIRouter(tags=["questionnaire-assignments"])
DB = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(current_user)]


def _doctor(db: Session, user: User, patient_id: str) -> None:
    if user.role != "doctor":
        raise HTTPException(403, "Требуется роль врача")
    if (
        db.scalar(
            select(Patient.id).where(
                Patient.id == patient_id,
                Patient.deleted_at.is_(None),
            )
        )
        is None
    ):
        raise HTTPException(404, "Пациент не найден")
    require_patient(db, user, patient_id)


def _patient(user: User) -> None:
    if user.role != "patient":
        raise HTTPException(403, "Требуется роль пациента")


@router.get("/questionnaire-catalog", response_model=list[TestCatalogEntry])
def catalog(user: Actor):
    if user.role not in {"doctor", "patient"}:
        raise HTTPException(403, "Недоступно")
    return service.catalog()


@router.get("/patients/me/questionnaire-assignments", response_model=list[TestAssignmentRead])
def own_assignments(db: DB, user: Actor):
    _patient(user)
    return service.list_own(db, user.id)


@router.post(
    "/patients/me/questionnaire-assignments/{assignment_id}/submit",
    response_model=TestAssignmentRead,
)
def own_submit(assignment_id: str, payload: SubmitDemoTest, db: DB, user: Actor):
    _patient(user)
    return service.submit(db, user.id, assignment_id, payload)


@router.get(
    "/patients/{patient_id}/questionnaire-assignments",
    response_model=list[DoctorTestAssignmentRead],
)
def doctor_assignments(patient_id: str, db: DB, user: Actor):
    _doctor(db, user, patient_id)
    return service.list_doctor(db, patient_id)


@router.post(
    "/patients/{patient_id}/questionnaire-assignments",
    response_model=DoctorTestAssignmentRead,
    status_code=201,
)
def assign(patient_id: str, payload: AssignDemoTest, db: DB, user: Actor):
    _doctor(db, user, patient_id)
    return service.assign(db, patient_id, user.id, payload)


@router.post(
    "/patients/{patient_id}/questionnaire-assignments/{assignment_id}/cancel",
    response_model=DoctorTestAssignmentRead,
)
def cancel(patient_id: str, assignment_id: str, payload: CancelDemoTest, db: DB, user: Actor):
    _doctor(db, user, patient_id)
    return service.cancel(db, patient_id, assignment_id, user.id, payload)
