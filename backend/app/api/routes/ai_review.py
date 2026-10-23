"""UI-4B: защищённое согласование синтетических тестовых предложений."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.api.routes.ai_workspace import _authorize
from app.db.session import get_db
from app.models.access import User
from app.schemas.ai_review import DraftImport, DraftRead, RejectDraft, ReviewAction, ReviewCommit
from app.services import ai_review as svc

router = APIRouter(tags=["ai-review-demo"])
DB = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(current_user)]


def _guard(db: Session, actor: User, patient_id: str, response: Response) -> None:
    _authorize(db, actor, patient_id)
    response.headers["Cache-Control"] = "private, no-store"


@router.get("/patients/{patient_id}/ai-requests/{request_id}/review", response_model=DraftRead)
def review_detail(patient_id: str, request_id: str, db: DB, actor: Actor, response: Response):
    _guard(db, actor, patient_id, response)
    return svc.get_draft(db, patient_id, actor.id, request_id)


@router.get(
    "/patients/{patient_id}/ai-requests/{request_id}/review/versions/{version}",
    response_model=DraftRead,
)
def historical_version(
    patient_id: str, request_id: str, version: int, db: DB, actor: Actor, response: Response
):
    _guard(db, actor, patient_id, response)
    return svc.get_historical_version(db, patient_id, actor.id, request_id, version)


@router.post(
    "/patients/{patient_id}/ai-requests/{request_id}/review",
    response_model=DraftRead,
    status_code=201,
)
def import_test_draft(
    patient_id: str, request_id: str, payload: DraftImport, db: DB, actor: Actor, response: Response
):
    _guard(db, actor, patient_id, response)
    return svc.import_draft(db, patient_id, actor.id, request_id, payload)


@router.post("/patients/{patient_id}/ai-requests/{request_id}/review/preview")
def preview(
    patient_id: str,
    request_id: str,
    payload: ReviewAction,
    db: DB,
    actor: Actor,
    response: Response,
):
    _guard(db, actor, patient_id, response)
    return svc.preview(db, patient_id, actor.id, request_id, payload)


@router.post("/patients/{patient_id}/ai-requests/{request_id}/review/approve")
def approve(
    patient_id: str,
    request_id: str,
    payload: ReviewCommit,
    db: DB,
    actor: Actor,
    response: Response,
):
    _guard(db, actor, patient_id, response)
    return svc.approve(db, patient_id, actor.id, request_id, payload)


@router.post(
    "/patients/{patient_id}/ai-requests/{request_id}/review/reject", response_model=DraftRead
)
def reject(
    patient_id: str, request_id: str, payload: RejectDraft, db: DB, actor: Actor, response: Response
):
    _guard(db, actor, patient_id, response)
    return svc.reject(db, patient_id, actor.id, request_id, payload)
