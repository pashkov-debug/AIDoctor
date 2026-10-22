"""Приватная стартовая страница пациента UI-1B.

Контракт намеренно допускает только явный allowlist полей.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.db.session import get_db
from app.models.access import User
from app.models.patient import Patient
from app.schemas.patient_portal import PatientPortalRead

router = APIRouter(prefix="/patients/me", tags=["patient-portal"])


@router.get("/portal", response_model=PatientPortalRead)
def my_patient_portal(
    user: Annotated[User, Depends(current_user)],
    session: Annotated[Session, Depends(get_db)],
) -> PatientPortalRead:
    """Пациент видит только свою активную карточку; никакой ID не вводится."""
    if user.role != "patient":
        raise HTTPException(status_code=403, detail="Patient role required")

    patient = session.scalar(
        select(Patient).where(
            Patient.user_id == user.id,
            Patient.deleted_at.is_(None),
        )
    )
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient account not linked")

    return PatientPortalRead(
        patient_id=patient.id,
        alias=patient.alias,
        created_at=patient.created_at,
    )
