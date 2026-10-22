"""Настройки канала in_app: врач управляет только своим маршрутом."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.access import require_doctor, require_patient
from app.db.session import get_db
from app.models.access import User
from app.schemas.safety_notification_route import (
    NotificationRouteChange,
    NotificationRouteRead,
)
from app.services.safety_notification_routes import (
    RouteAccessDenied,
    configure_own_route,
    get_own_route,
)
from app.services.safety_read_audit import record_safety_read

router = APIRouter(tags=["safety-notification-routes"])
SessionDependency = Annotated[Session, Depends(get_db)]
UserDependency = Annotated[User, Depends(current_user)]


def _authorized_route(patient_id: str, session: SessionDependency, user: UserDependency) -> str:
    require_doctor(user)
    require_patient(session, user, patient_id)
    # Администратор не может подтвердить чужую учётную запись вместо врача.
    if user.role != "doctor":
        raise HTTPException(status_code=403, detail="Doctor account required")
    return patient_id


@router.get(
    "/patients/{patient_id}/safety-notification-route",
    response_model=NotificationRouteRead | None,
    summary="Собственная настройка маршрута in_app",
)
def get_route(
    patient_id: Annotated[str, Depends(_authorized_route)],
    session: SessionDependency,
    user: UserDependency,
) -> NotificationRouteRead | None:
    try:
        result = get_own_route(session, patient_id=patient_id, actor_id=user.id)
    except RouteAccessDenied as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc
    serialized = NotificationRouteRead.model_validate(result) if result is not None else None
    record_safety_read(
        session,
        actor_id=user.id,
        scope="route_read",
        patient_id=patient_id,
        returned_count=int(result is not None),
    )
    return serialized


@router.put(
    "/patients/{patient_id}/safety-notification-route",
    response_model=NotificationRouteRead,
    summary="Включить или отключить собственный внутренний маршрут",
)
def put_route(
    data: NotificationRouteChange,
    patient_id: Annotated[str, Depends(_authorized_route)],
    session: SessionDependency,
    user: UserDependency,
) -> NotificationRouteRead:
    try:
        result = configure_own_route(
            session, patient_id=patient_id, actor_id=user.id, enabled=data.enabled
        )
    except RouteAccessDenied as exc:
        raise HTTPException(status_code=404, detail="Patient not found") from exc
    return NotificationRouteRead.model_validate(result)
