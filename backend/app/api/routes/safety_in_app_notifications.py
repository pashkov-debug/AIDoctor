"""Чтение собственного inbox врача; отсутствие доступа скрывает уведомления."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.db.session import get_db
from app.models.access import User
from app.schemas.safety_in_app_notification import SafetyInAppNotificationRead
from app.services.safety_in_app_delivery import list_own_inbox
from app.services.safety_read_audit import record_safety_read

router = APIRouter(tags=["safety-in-app-notifications"])
SessionDependency = Annotated[Session, Depends(get_db)]
UserDependency = Annotated[User, Depends(current_user)]


@router.get(
    "/safety-inbox",
    response_model=list[SafetyInAppNotificationRead],
    summary="Последние внутренние уведомления текущего врача",
)
def get_own_safety_inbox(
    session: SessionDependency,
    user: UserDependency,
) -> list[SafetyInAppNotificationRead]:
    if user.role != "doctor":
        raise HTTPException(status_code=403, detail="Doctor account required")
    notifications = list_own_inbox(session, recipient_user_id=user.id)
    result = [SafetyInAppNotificationRead.model_validate(item) for item in notifications]
    record_safety_read(
        session, actor_id=user.id, scope="inbox_list",
        returned_count=len(notifications),
    )
    return result
