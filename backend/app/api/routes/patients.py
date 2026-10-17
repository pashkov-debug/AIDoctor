from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.access import require_doctor, require_patient
from app.db.session import get_db
from app.models.access import User
from app.schemas.patient import PatientCreate, PatientListResponse, PatientRead
from app.services.patient import PatientNotFoundError, PatientService

router = APIRouter(prefix="/patients", tags=["patients"])

SessionDependency = Annotated[Session, Depends(get_db)]
UserDependency = Annotated[User, Depends(current_user)]
SearchQuery = Annotated[
    str | None,
    Query(
        max_length=100,
        description="Поиск по alias или local patient id",
    ),
]


@router.post(
    "",
    response_model=PatientRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать пациента",
)
def create_patient(
    payload: PatientCreate,
    session: SessionDependency,
    user: UserDependency,
) -> PatientRead:
    require_doctor(user)
    service = PatientService(session)
    return service.create_patient(payload, created_by=user)


@router.get(
    "",
    response_model=PatientListResponse,
    summary="Получить список доступных пациентов",
)
def list_patients(
    session: SessionDependency,
    user: UserDependency,
    search: SearchQuery = None,
) -> PatientListResponse:
    service = PatientService(session)
    return service.list_patients(actor=user, search=search)


@router.get(
    "/{patient_id}",
    response_model=PatientRead,
    summary="Получить пациента",
)
def get_patient(
    patient_id: str,
    session: SessionDependency,
    user: UserDependency,
) -> PatientRead:
    require_patient(session, user, patient_id)
    service = PatientService(session)
    try:
        return service.get_patient(patient_id)
    except PatientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        ) from exc
