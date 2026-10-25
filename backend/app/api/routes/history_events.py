from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    status,
)
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.access import require_active_doctor_patient, require_doctor, require_patient
from app.db.session import get_db
from app.models.access import User
from app.schemas.clinical_entry import ManualHistoryCreate
from app.schemas.history_event import (
    HistoryEventList,
    HistoryEventRead,
)
from app.services.clinical_entries import create_history
from app.services.history_event import (
    HistoryEventService,
    HistoryPatientNotFoundError,
)

router = APIRouter(
    dependencies=[Depends(current_user)],
    tags=["history"],
)

SessionDependency = Annotated[
    Session,
    Depends(get_db),
]


@router.get(
    "/patients/{patient_id}/history-events",
    response_model=HistoryEventList,
    summary="Получить продольную историю пациента",
)
def list_history_events(
    patient_id: str,
    session: SessionDependency,
    user: Annotated[User, Depends(current_user)],
    response: Response,
) -> HistoryEventList:
    # Внутренние клинические события не публикуются пациенту без отдельной политики.
    require_doctor(user)
    require_patient(session, user, patient_id)
    response.headers["Cache-Control"] = "private, no-store"
    service = HistoryEventService(session)

    try:
        return service.list_patient_events(patient_id)

    except HistoryPatientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        ) from exc


@router.post(
    "/patients/{patient_id}/history-events",
    response_model=HistoryEventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить врачебную запись в историю",
)
def create_history_event(
    patient_id: str,
    payload: ManualHistoryCreate,
    session: SessionDependency,
    user: Annotated[User, Depends(current_user)],
    response: Response,
) -> HistoryEventRead:
    require_active_doctor_patient(session, user, patient_id)
    response.headers["Cache-Control"] = "private, no-store"
    return create_history(session, patient_id, user.id, payload)
