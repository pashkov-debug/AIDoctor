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
from app.schemas.questionnaire import (
    QuestionnaireResponseCreate,
    QuestionnaireResponseList,
    QuestionnaireResponseRead,
)
from app.services.questionnaire import (
    InvalidScaleResponseError,
    QuestionnaireEncounterNotFoundError,
    QuestionnaireService,
    ScaleNotFoundError,
)

router = APIRouter(
    tags=["questionnaires"],
)

SessionDependency = Annotated[
    Session,
    Depends(get_db),
]


@router.post(
    "/encounters/{encounter_id}/questionnaires",
    response_model=QuestionnaireResponseRead,
    status_code=status.HTTP_201_CREATED,
    summary="Сохранить результат шкалы",
)
def create_questionnaire_response(
    encounter_id: str,
    payload: QuestionnaireResponseCreate,
    session: SessionDependency,
) -> QuestionnaireResponseRead:
    service = QuestionnaireService(session)

    try:
        return service.create_response(
            encounter_id,
            payload,
        )

    except QuestionnaireEncounterNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Encounter not found",
        ) from exc

    except ScaleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported scale",
        ) from exc

    except InvalidScaleResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/patients/{patient_id}/questionnaires",
    response_model=QuestionnaireResponseList,
    summary="Получить историю шкал пациента",
)
def list_questionnaire_responses(
    patient_id: str,
    session: SessionDependency,
    scale_id: Annotated[
        str | None,
        Query(max_length=50),
    ] = None,
) -> QuestionnaireResponseList:
    service = QuestionnaireService(session)

    return service.list_patient_responses(
        patient_id,
        scale_id=scale_id,
    )
