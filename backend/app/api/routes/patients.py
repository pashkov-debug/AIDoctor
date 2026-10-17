from app.api.auth import current_user
from app.models.access import User, DoctorPatient
from app.models.patient import Patient
from app.schemas.patient import PatientListResponse
from sqlalchemy import select
from app.core.access import require_patient, require_encounter, require_doctor
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.patient import (
    PatientCreate,
    PatientListResponse,
    PatientRead,
)
from app.services.patient import (
    PatientNotFoundError,
    PatientService,
)

router = APIRouter(dependencies=[Depends(current_user)],
    prefix="/patients",
    tags=["patients"],
)

SessionDependency = Annotated[
    Session,
    Depends(get_db),
]

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
    user: Annotated[User, Depends(current_user)],
) -> PatientRead:
    require_doctor(user)
    service = PatientService(session)

    result = service.create_patient(payload)
    if user.role == "doctor":
        session.add(DoctorPatient(doctor_id=user.id, patient_id=result.id))
        session.commit()
    return result


@router.get(
    "",
    response_model=PatientListResponse,
    summary="Получить список пациентов",
)
def list_patients(
    session: SessionDependency,
    user: Annotated[User, Depends(current_user)],
    search: SearchQuery = None,
) -> PatientListResponse:
    service = PatientService(session)
    if user.role == "admin":
        return service.list_patients(search=search)
    if user.role == "doctor":
        ids = session.scalars(select(DoctorPatient.patient_id).where(DoctorPatient.doctor_id == user.id)).all()
    else:
        ids = session.scalars(select(Patient.id).where(Patient.user_id == user.id)).all()
    items = []
    for patient_id in ids:
        try:
            patient = service.get_patient(patient_id)
            if search is None or search.lower() in patient.alias.lower() or search.lower() in patient.id.lower():
                items.append(patient)
        except PatientNotFoundError:
            continue
    return PatientListResponse(items=items, total=len(items))


@router.get(
    "/{patient_id}",
    response_model=PatientRead,
    summary="Получить пациента",
)
def get_patient(
    patient_id: str,
    session: SessionDependency,
    user: Annotated[User, Depends(current_user)],
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
