"""Read-only контекст для врачебной проверки; не отправлять во внешний LLM."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.access import require_doctor, require_patient
from app.db.session import get_db
from app.models.access import User
from app.services.context_builder import (
    ClinicalContext,
    ContextBuilder,
    ContextPatientNotFoundError,
)

router = APIRouter(tags=["context"])


@router.get(
    "/patients/{patient_id}/context",
    response_model=ClinicalContext,
    summary="Структурированный медицинский контекст пациента",
)
def get_patient_context(
    patient_id: str,
    session: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(current_user)],
) -> ClinicalContext:
    require_doctor(user)
    require_patient(session, user, patient_id)
    try:
        return ContextBuilder(session).build(patient_id)
    except ContextPatientNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc
