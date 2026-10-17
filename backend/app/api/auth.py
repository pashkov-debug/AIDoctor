from typing import Annotated
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.access import User
from app.models.auth_session import AuthSession
import hashlib
from datetime import datetime, timezone

bearer = HTTPBearer(auto_error=False)

def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required",
                            headers={"WWW-Authenticate": "Bearer"})
    token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    active = session.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash))
    if active is None or active.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = session.get(User, active.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user
