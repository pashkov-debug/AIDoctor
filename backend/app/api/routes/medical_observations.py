"""Ручные медицинские наблюдения в существующей таблице."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.access import require_active_doctor_patient
from app.db.session import get_db
from app.models.access import User
from app.schemas.clinical_entry import (
    ManualObservationCreate,
    ObservationList,
    ObservationRead,
)
from app.services.clinical_entries import create_observation, list_observations

router = APIRouter(tags=["medical-observations"])
DB = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(current_user)]


@router.get("/patients/{patient_id}/observations", response_model=ObservationList)
def get_observations(patient_id: str, db: DB, actor: Actor, response: Response):
    require_active_doctor_patient(db, actor, patient_id)
    response.headers["Cache-Control"] = "private, no-store"
    return list_observations(db, patient_id)


@router.post(
    "/patients/{patient_id}/observations",
    response_model=ObservationRead,
    status_code=status.HTTP_201_CREATED,
)
def post_observation(
    patient_id: str,
    payload: ManualObservationCreate,
    db: DB,
    actor: Actor,
    response: Response,
):
    require_active_doctor_patient(db, actor, patient_id)
    response.headers["Cache-Control"] = "private, no-store"
    return create_observation(db, patient_id, actor.id, payload)
