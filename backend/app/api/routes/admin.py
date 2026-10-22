"""UI-1C: административные списки и безопасные команды в PostgreSQL."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.security import hash_password
from app.db.session import get_db
from app.models.access import DoctorPatient, User
from app.models.admin_audit import AdminAuditEvent
from app.models.patient import Patient
from app.schemas.admin import (
    AccessLinkRead,
    AccountRead,
    AdminAuditRead,
    AdminPatientRead,
    CreateAccount,
    CreateSyntheticPatient,
)
from app.services.admin_audit import record_admin_action

router = APIRouter(prefix="/admin", tags=["admin"])
Db = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(current_user)]


def require_admin(actor: User) -> None:
    if actor.role != "admin":
        raise HTTPException(status_code=403, detail="Admin required")


@router.get("/users", response_model=list[AccountRead])
def list_accounts(db: Db, actor: Actor) -> list[AccountRead]:
    require_admin(actor)
    users = db.scalars(select(User).order_by(User.username, User.id).limit(500)).all()
    return [
        AccountRead(id=u.id, username=u.username, role=u.role, created_at=u.created_at)
        for u in users
    ]


@router.post("/users", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(payload: CreateAccount, db: Db, actor: Actor) -> AccountRead:
    require_admin(actor)
    account = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
    )
    try:
        db.add(account)
        db.flush()
        record_admin_action(
            db,
            actor_id=actor.id,
            action="user_created",
            target_id=account.id,
            details={"role": account.role, "username": account.username},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Логин уже занят") from exc
    db.refresh(account)
    return AccountRead(
        id=account.id,
        username=account.username,
        role=account.role,
        created_at=account.created_at,
    )


@router.get("/patients", response_model=list[AdminPatientRead])
def list_patient_cards(db: Db, actor: Actor) -> list[AdminPatientRead]:
    require_admin(actor)
    patients = db.scalars(
        select(Patient)
        .where(Patient.deleted_at.is_(None))
        .order_by(Patient.alias, Patient.id)
        .limit(500)
    ).all()
    return [
        AdminPatientRead(
            id=p.id,
            alias=p.alias,
            synthetic=(p.demographics_json or {}).get("synthetic") is True,
            user_id=p.user_id,
        )
        for p in patients
    ]


@router.post(
    "/synthetic-patients",
    response_model=AdminPatientRead,
    status_code=status.HTTP_201_CREATED,
)
def create_synthetic_patient(
    payload: CreateSyntheticPatient, db: Db, actor: Actor
) -> AdminPatientRead:
    require_admin(actor)
    patient = Patient(alias=payload.alias, demographics_json={"synthetic": True})
    db.add(patient)
    db.flush()
    record_admin_action(
        db,
        actor_id=actor.id,
        action="synthetic_patient_created",
        target_id=patient.id,
        details={"alias": patient.alias},
    )
    db.commit()
    return AdminPatientRead(id=patient.id, alias=patient.alias, synthetic=True, user_id=None)


@router.get("/links", response_model=list[AccessLinkRead])
def list_links(db: Db, actor: Actor) -> list[AccessLinkRead]:
    require_admin(actor)
    links = db.scalars(
        select(DoctorPatient)
        .join(Patient, DoctorPatient.patient_id == Patient.id)
        .where(Patient.deleted_at.is_(None))
        .order_by(DoctorPatient.created_at.desc(), DoctorPatient.id)
        .limit(500)
    ).all()
    return [
        AccessLinkRead(
            id=link.id,
            doctor_id=link.doctor_id,
            patient_id=link.patient_id,
            created_at=link.created_at,
        )
        for link in links
    ]


@router.delete("/links/{link_id}", status_code=204)
def unlink_doctor_patient(link_id: str, db: Db, actor: Actor) -> None:
    require_admin(actor)
    link = db.get(DoctorPatient, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Связь не найдена")
    record_admin_action(
        db,
        actor_id=actor.id,
        action="doctor_patient_unlinked",
        target_id=link.id,
        details={"doctor_id": link.doctor_id, "patient_id": link.patient_id},
    )
    db.delete(link)
    db.commit()


@router.get("/audit", response_model=list[AdminAuditRead])
def list_admin_audit(db: Db, actor: Actor) -> list[AdminAuditRead]:
    require_admin(actor)
    events = db.scalars(
        select(AdminAuditEvent)
        .order_by(AdminAuditEvent.created_at.desc(), AdminAuditEvent.id.desc())
        .limit(50)
    ).all()
    return [
        AdminAuditRead(
            id=e.id,
            actor_id=e.actor_id,
            action=e.action,
            target_id=e.target_id,
            details=e.details_json,
            created_at=e.created_at,
        )
        for e in events
    ]
