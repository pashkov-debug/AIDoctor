from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.history_event import (
    HistoryEventList,
)
from app.services.history_event import (
    HistoryEventService,
    HistoryPatientNotFoundError,
)

router = APIRouter(
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
) -> HistoryEventList:
    service = HistoryEventService(session)

    try:
        return service.list_patient_events(patient_id)

    except HistoryPatientNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient not found",
        ) from exc
