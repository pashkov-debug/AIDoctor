"""Авторизованный доступ к контексту, Digest и Delta; без передачи данных LLM."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
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
from app.services.context_delta import (
    ContextDelta,
    SnapshotValidationError,
    compare_contexts,
)
from app.services.context_digest import ContextDigest, build_digest

router = APIRouter(tags=["context"])
SessionDependency = Annotated[Session, Depends(get_db)]
UserDependency = Annotated[User, Depends(current_user)]


class CompareContextRequest(BaseModel):
    baseline: ClinicalContext


def _authorized_context(
    patient_id: str,
    session: SessionDependency,
    user: UserDependency,
) -> ClinicalContext:
    # Проверка права должна происходить до чтения данных и до обработки baseline.
    require_doctor(user)
    require_patient(session, user, patient_id)
    try:
        return ContextBuilder(session).build(patient_id)
    except ContextPatientNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc


@router.get(
    "/patients/{patient_id}/context",
    response_model=ClinicalContext,
    summary="Структурированный медицинский контекст пациента",
)
def get_patient_context(
    patient_id: str,
    session: SessionDependency,
    user: UserDependency,
) -> ClinicalContext:
    return _authorized_context(patient_id, session, user)


@router.get(
    "/patients/{patient_id}/context/digest",
    response_model=ContextDigest,
    summary="Состав и даты фактов без клинических интерпретаций",
)
def get_context_digest(
    patient_id: str,
    session: SessionDependency,
    user: UserDependency,
) -> ContextDigest:
    return build_digest(_authorized_context(patient_id, session, user))


@router.post(
    "/patients/{patient_id}/context/delta",
    response_model=ContextDelta,
    summary="Сравнение переданного снимка с текущим контекстом",
)
def compare_patient_context(
    request: CompareContextRequest,
    current: Annotated[ClinicalContext, Depends(_authorized_context)],
) -> ContextDelta:
    # FastAPI выполняет зависимости до валидации Pydantic-модели тела:
    # посторонний врач получит 404 даже при {"baseline": {}}.
    try:
        return compare_contexts(request.baseline, current)
    except SnapshotValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
