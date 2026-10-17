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
from app.services.context_snapshots import (
    SnapshotIntegrityError,
    SnapshotNotFoundError,
    SnapshotSummary,
    SnapshotWithContext,
    create_snapshot,
    get_snapshot,
    list_snapshots,
)

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


@router.post(
    "/patients/{patient_id}/context/snapshots",
    response_model=SnapshotSummary,
    status_code=201,
    summary="Сохранить неизменяемый снимок контекста на сервере",
)
def save_patient_context_snapshot(
    current: Annotated[ClinicalContext, Depends(_authorized_context)],
    session: SessionDependency,
    user: UserDependency,
) -> SnapshotSummary:
    try:
        return create_snapshot(session, current, user.id)
    except SnapshotIntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/patients/{patient_id}/context/snapshots",
    response_model=list[SnapshotSummary],
    summary="Последние 50 серверных снимков пациента",
)
def list_patient_context_snapshots(
    patient_id: str,
    current: Annotated[ClinicalContext, Depends(_authorized_context)],
    session: SessionDependency,
) -> list[SnapshotSummary]:
    # current используется как проверка права и существования активного пациента.
    return list_snapshots(session, current.patient_id)


@router.get(
    "/patients/{patient_id}/context/snapshots/{snapshot_id}",
    response_model=SnapshotWithContext,
    summary="Получить серверный снимок пациента",
)
def get_patient_context_snapshot(
    snapshot_id: str,
    current: Annotated[ClinicalContext, Depends(_authorized_context)],
    session: SessionDependency,
) -> SnapshotWithContext:
    try:
        return get_snapshot(session, current.patient_id, snapshot_id)
    except SnapshotNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Snapshot not found") from exc
    except SnapshotIntegrityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/patients/{patient_id}/context/snapshots/{snapshot_id}/delta",
    response_model=ContextDelta,
    summary="Сравнить сохранённый снимок с текущим контекстом",
)
def compare_patient_snapshot(
    snapshot_id: str,
    current: Annotated[ClinicalContext, Depends(_authorized_context)],
    session: SessionDependency,
) -> ContextDelta:
    try:
        baseline = get_snapshot(session, current.patient_id, snapshot_id).context
        return compare_contexts(baseline, current)
    except SnapshotNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Snapshot not found") from exc
    except (SnapshotIntegrityError, SnapshotValidationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
