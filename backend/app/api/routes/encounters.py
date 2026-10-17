from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.access import require_doctor, require_encounter, require_patient
from app.db.session import get_db
from app.models.access import User
from app.schemas.encounter import (
    EncounterCreate,
    EncounterListResponse,
    EncounterRead,
)
from app.services.encounter import (
    EncounterNotFoundError,
    EncounterPatientNotFoundError,
    EncounterService,
)

router = APIRouter(
    dependencies=[Depends(current_user)],
    tags=["encounters"],
)

SessionDependency = Annotated[
    Session,
    Depends(get_db),
]


@router.post(
    "/patients/{patient_id}/encounters",
    response_model=EncounterRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать визит пациента",
)
def create_encounter(
    patient_id: str,
    payload: EncounterCreate,
    session: SessionDependency,
    user: Annotated[User, Depends(current_user)],
) -> EncounterRead:
    require_doctor(user)
    require_patient(session, user, patient_id)
    service = EncounterService(session)

    try:
        return service.create_encounter(
            patient_id,
            payload,
        )

    except EncounterPatientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        ) from exc


@router.get(
    "/patients/{patient_id}/encounters",
    response_model=EncounterListResponse,
    summary="Получить визиты пациента",
)
def list_patient_encounters(
    patient_id: str,
    session: SessionDependency,
    user: Annotated[User, Depends(current_user)],
) -> EncounterListResponse:
    require_patient(session, user, patient_id)
    service = EncounterService(session)

    try:
        return service.list_patient_encounters(patient_id)

    except EncounterPatientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        ) from exc


@router.get(
    "/encounters/{encounter_id}",
    response_model=EncounterRead,
    summary="Получить визит",
)
def get_encounter(
    encounter_id: str,
    session: SessionDependency,
    user: Annotated[User, Depends(current_user)],
) -> EncounterRead:
    require_encounter(session, user, encounter_id)
    service = EncounterService(session)

    try:
        return service.get_encounter(encounter_id)

    except EncounterNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found",
        ) from exc
