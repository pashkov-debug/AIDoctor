import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.security import verify_password
from app.db.session import get_db
from app.models.access import User
from app.models.auth_session import AuthSession

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1)


@router.post("/login")
def login(payload: LoginRequest, session: Annotated[Session, Depends(get_db)]):
    user = session.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = secrets.token_urlsafe(48)
    session.add(
        AuthSession(
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(hours=8),
        )
    )
    session.commit()
    return {"access_token": token, "token_type": "bearer", "expires_in": 28800}


@router.get("/me")
def me(user: Annotated[User, Depends(current_user)]):
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/logout", status_code=204)
def logout(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[Session, Depends(get_db)],
):
    # Server-side logout of all sessions for this user; simple MVP policy.
    session.query(AuthSession).filter(AuthSession.user_id == user.id).delete()
    session.commit()
