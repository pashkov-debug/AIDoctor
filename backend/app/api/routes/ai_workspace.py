"""Врачебная рабочая область AI: сохранение подготовленных запросов без модели."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.access import require_patient
from app.db.session import get_db
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from app.schemas.ai_agent_context import AIAgentContextRead
from app.schemas.ai_workspace import AIRequestCreate, AIRequestRead, AIWorkspaceInfo
from app.services.ai_agent_context import get_agent_context
from app.services.ai_review import enabled_for_patient
from app.services.ai_workspace import create_request, get_request, list_requests

router = APIRouter(tags=["ai-workspace"])
DB = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(current_user)]


def _authorize(db: Session, actor: User, patient_id: str) -> None:
    if actor.role != "doctor":
        raise HTTPException(status_code=403, detail="Доступно только врачу")
    require_patient(db, actor, patient_id)
    exists = db.scalar(
        select(Patient.id)
        .where(Patient.id == patient_id, Patient.deleted_at.is_(None))
        .with_for_update(read=True)
    )
    if exists is None:
        raise HTTPException(status_code=404, detail="Пациент не найден")
    link = db.scalar(
        select(DoctorPatient.id)
        .where(DoctorPatient.doctor_id == actor.id, DoctorPatient.patient_id == patient_id)
        .with_for_update(read=True)
    )
    if link is None:
        raise HTTPException(status_code=404, detail="Связь с пациентом недоступна")


@router.get("/patients/{patient_id}/ai-workspace", response_model=AIWorkspaceInfo)
def workspace_info(patient_id: str, db: DB, actor: Actor, response: Response) -> AIWorkspaceInfo:
    _authorize(db, actor, patient_id)
    response.headers["Cache-Control"] = "private, no-store"
    return AIWorkspaceInfo(synthetic_review_enabled=enabled_for_patient(db, patient_id))


@router.get("/patients/{patient_id}/ai-requests", response_model=list[AIRequestRead])
def requests(patient_id: str, db: DB, actor: Actor, response: Response) -> list[AIRequestRead]:
    _authorize(db, actor, patient_id)
    response.headers["Cache-Control"] = "private, no-store"
    return list_requests(db, actor.id, patient_id)


@router.get("/patients/{patient_id}/ai-requests/{request_id}", response_model=AIRequestRead)
def request_detail(
    patient_id: str, request_id: str, db: DB, actor: Actor, response: Response
) -> AIRequestRead:
    _authorize(db, actor, patient_id)
    response.headers["Cache-Control"] = "private, no-store"
    return get_request(db, actor.id, patient_id, request_id)


@router.post("/patients/{patient_id}/ai-requests", status_code=201, response_model=AIRequestRead)
def prepare_request(
    patient_id: str, payload: AIRequestCreate, db: DB, actor: Actor, response: Response
) -> AIRequestRead:
    _authorize(db, actor, patient_id)
    response.headers["Cache-Control"] = "private, no-store"
    return create_request(db, actor.id, patient_id, payload)


@router.get(
    "/patients/{patient_id}/ai-requests/{request_id}/agent-context",
    response_model=AIAgentContextRead,
    summary="Сохранённый контекст для проверки проектов назначений (без отправки AI)",
)
def agent_context(
    patient_id: str, request_id: str, db: DB, actor: Actor, response: Response
) -> AIAgentContextRead:
    _authorize(db, actor, patient_id)
    response.headers["Cache-Control"] = "private, no-store"
    return get_agent_context(db, actor.id, patient_id, request_id)
