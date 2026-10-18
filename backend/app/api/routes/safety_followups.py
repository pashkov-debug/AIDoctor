"""Контрольный список непросмотренных сигналов для текущего врача."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.db.session import get_db
from app.models.access import User
from app.schemas.safety_followup import SafetyFollowupRead
from app.services.safety_followups import list_own_open_followups

router = APIRouter(tags=["safety-followups"])
SessionDependency = Annotated[Session, Depends(get_db)]
UserDependency = Annotated[User, Depends(current_user)]


@router.get(
    "/safety-followups",
    response_model=list[SafetyFollowupRead],
    summary="Просроченные неподтверждённые сигналы текущего врача",
)
def get_own_followups(
    session: SessionDependency,
    user: UserDependency,
) -> list[SafetyFollowupRead]:
    if user.role != "doctor":
        raise HTTPException(status_code=403, detail="Doctor account required")
    return [
        SafetyFollowupRead.model_validate(item)
        for item in list_own_open_followups(
            session, recipient_user_id=user.id
        )
    ]
