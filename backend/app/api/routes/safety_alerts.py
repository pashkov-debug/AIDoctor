"""Сигналы врачебной проверки: не являются каналом экстренной помощи."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.access import require_doctor, require_patient
from app.db.session import get_db
from app.models.access import User
from app.models.patient import Patient
from app.schemas.safety_alert import SafetyAlertCreate, SafetyAlertRead
from app.services.safety_alerts import (
    AlertNotFoundError,
    IdempotencyConflict,
    InvalidIdempotencyKey,
    acknowledge_alert,
    create_alert,
    list_alerts,
)
from app.services.safety_read_audit import record_safety_read

router = APIRouter(tags=["safety-alerts"])
SessionDependency = Annotated[Session, Depends(get_db)]
UserDependency = Annotated[User, Depends(current_user)]


def _authorized_clinician(
    patient_id: str, session: SessionDependency, user: UserDependency
) -> str:
    # Проверка как зависимость: до Pydantic-валидации тела запроса.
    require_doctor(user)
    require_patient(session, user, patient_id)
    patient = session.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient_id


@router.post(
    "/patients/{patient_id}/safety-alerts",
    response_model=SafetyAlertRead,
    status_code=201,
    summary="Создать ручной сигнал для врачебной проверки",
)
def post_safety_alert(
    data: SafetyAlertCreate,
    patient_id: Annotated[str, Depends(_authorized_clinician)],
    session: SessionDependency,
    user: UserDependency,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> SafetyAlertRead:
    try:
        alert = create_alert(
            session,
            patient_id,
            user.id,
            data,
            idempotency_key=idempotency_key,
        )
    except InvalidIdempotencyKey as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return SafetyAlertRead.model_validate(alert)


@router.get(
    "/patients/{patient_id}/safety-alerts",
    response_model=list[SafetyAlertRead],
    summary="Последние 100 сигналов пациента для врача",
)
def get_safety_alerts(
    patient_id: Annotated[str, Depends(_authorized_clinician)],
    session: SessionDependency,
    user: UserDependency,
) -> list[SafetyAlertRead]:
    alerts = list_alerts(session, patient_id)
    result = [SafetyAlertRead.model_validate(item) for item in alerts]
    record_safety_read(
        session, actor_id=user.id, scope="alerts_list",
        patient_id=patient_id, returned_count=len(alerts),
    )
    return result


@router.post(
    "/patients/{patient_id}/safety-alerts/{alert_id}/ack",
    response_model=SafetyAlertRead,
    summary="Подтвердить просмотр сигнала",
)
def post_safety_alert_ack(
    alert_id: str,
    patient_id: Annotated[str, Depends(_authorized_clinician)],
    session: SessionDependency,
    user: UserDependency,
) -> SafetyAlertRead:
    try:
        alert = acknowledge_alert(session, patient_id, alert_id, user.id)
    except AlertNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Alert not found") from exc
    return SafetyAlertRead.model_validate(alert)
