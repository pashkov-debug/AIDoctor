"""UI-3A: только ручные назначения, без AI и автоматического утверждения."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.clinical.medication_safety import check_order_regimen
from app.core.access import require_patient
from app.db.session import get_db
from app.models.access import User
from app.models.patient import Patient
from app.schemas.clinical_order import (
    OrderApprove,
    OrderCancel,
    OrderDraftCreate,
    OrderRead,
    OrderUpdate,
    PatientOrdersList,
)
from app.services import clinical_order as service

router = APIRouter(tags=["clinical-orders"])
DB = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(current_user)]


def _doctor_patient(db: Session, actor: User, patient_id: str) -> None:
    if actor.role != "doctor":
        raise HTTPException(403, detail="Требуется роль врача")
    exists = db.scalar(
        select(Patient.id).where(
            Patient.id == patient_id,
            Patient.deleted_at.is_(None),
        )
    )
    if exists is None:
        raise HTTPException(404, detail="Пациент не найден")
    require_patient(db, actor, patient_id)


@router.get("/patients/me/clinical-orders", response_model=PatientOrdersList)
def own_orders(db: DB, actor: Actor):
    if actor.role != "patient":
        raise HTTPException(403, detail="Требуется роль пациента")
    return service.patient_list(db, actor.id)


@router.get("/patients/{patient_id}/clinical-orders", response_model=list[OrderRead])
def doctor_orders(patient_id: str, db: DB, actor: Actor):
    _doctor_patient(db, actor, patient_id)
    return service.doctor_list(db, patient_id)


@router.get("/patients/{patient_id}/clinical-orders/safety-alerts")
def doctor_order_safety_alerts(patient_id: str, db: DB, actor: Actor) -> list[dict]:
    """Текущие предупреждения, без изменений и назначения лечения."""
    _doctor_patient(db, actor, patient_id)
    alerts = []
    for order in service.doctor_list(db, patient_id):
        if order.status == "cancelled" or order.kind != "medication":
            continue
        alert = check_order_regimen(
            name=order.name,
            active_ingredient=order.active_ingredient,
            dose_value=order.dose_value,
            dose_unit=order.dose_unit,
            frequency_per_day=order.frequency_per_day,
        )
        if alert:
            alerts.append(
                {
                    **alert,
                    "order_id": order.id,
                    "order_status": order.status,
                    "order_name": order.name,
                    "source_kind": "deterministic_rule_not_ai",
                }
            )
    return alerts


@router.post(
    "/patients/{patient_id}/clinical-orders",
    response_model=OrderRead,
    status_code=status.HTTP_201_CREATED,
)
def create_order(patient_id: str, payload: OrderDraftCreate, db: DB, actor: Actor):
    _doctor_patient(db, actor, patient_id)
    return service.create(db, patient_id, actor.id, payload)


@router.put("/patients/{patient_id}/clinical-orders/{order_id}", response_model=OrderRead)
def update_order(patient_id: str, order_id: str, payload: OrderUpdate, db: DB, actor: Actor):
    _doctor_patient(db, actor, patient_id)
    return service.update(db, patient_id, order_id, actor.id, payload)


@router.post("/patients/{patient_id}/clinical-orders/{order_id}/approve", response_model=OrderRead)
def approve_order(patient_id: str, order_id: str, payload: OrderApprove, db: DB, actor: Actor):
    _doctor_patient(db, actor, patient_id)
    return service.approve(db, patient_id, order_id, actor.id, payload)


@router.post("/patients/{patient_id}/clinical-orders/{order_id}/cancel", response_model=OrderRead)
def cancel_order(patient_id: str, order_id: str, payload: OrderCancel, db: DB, actor: Actor):
    _doctor_patient(db, actor, patient_id)
    return service.cancel(db, patient_id, order_id, actor.id, payload)
