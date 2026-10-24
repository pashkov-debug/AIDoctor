"""Назначения: ручной черновик, поэлементное утверждение, отмена и аудит."""

from uuid import UUID

from app.db.base import utc_now
from app.models.clinical_order import ClinicalOrder, ClinicalOrderAudit
from app.models.patient import Patient
from app.schemas.clinical_order import (
    OrderApprove,
    OrderCancel,
    OrderDraftCreate,
    OrderRead,
    OrderUpdate,
    PatientOrderRead,
    PatientOrdersList,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def _read(record: ClinicalOrder) -> OrderRead:
    result = OrderRead.model_validate(record, from_attributes=True)
    return result


def _snapshot(record: ClinicalOrder) -> dict:
    # Копия каждого состояния в журнале. Исправления истории невозможны через API.
    return _read(record).model_dump(mode="json")


def _audit(db: Session, record: ClinicalOrder, actor_id: str, action: str) -> None:
    db.add(
        ClinicalOrderAudit(
            order_id=record.id,
            actor_id=actor_id,
            action=action,
            version=record.version,
            snapshot_json=_snapshot(record),
        )
    )


def _same_payload(record: ClinicalOrder, payload: OrderDraftCreate) -> bool:
    fields = OrderDraftCreate.model_fields
    saved = {name: getattr(record, name) for name in fields}
    saved["request_key"] = UUID(saved["request_key"])
    return OrderDraftCreate.model_validate(saved) == payload


def create(db: Session, patient_id: str, actor_id: str, payload: OrderDraftCreate) -> OrderRead:
    request_key = str(payload.request_key)
    existing = db.scalar(
        select(ClinicalOrder).where(
            ClinicalOrder.author_id == actor_id,
            ClinicalOrder.request_key == request_key,
        )
    )
    if existing:
        if existing.patient_id != patient_id or not _same_payload(existing, payload):
            raise HTTPException(409, detail="Ключ запроса использован для другого назначения")
        return _read(existing)
    fields = payload.model_dump(exclude={"request_key"})
    record = ClinicalOrder(
        **fields,
        request_key=request_key,
        patient_id=patient_id,
        author_id=actor_id,
        status="draft",
        version=1,
    )
    # kind включён в fields; передаём его ровно один раз.
    db.add(record)
    try:
        db.flush()
        _audit(db, record, actor_id, "draft_created")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        replay = db.scalar(
            select(ClinicalOrder).where(
                ClinicalOrder.author_id == actor_id,
                ClinicalOrder.request_key == request_key,
            )
        )
        if (
            replay is not None
            and replay.patient_id == patient_id
            and _same_payload(replay, payload)
        ):
            return _read(replay)
        raise HTTPException(409, detail="Повторный ключ запроса") from exc
    except Exception:
        db.rollback()
        raise
    return _read(record)


def doctor_list(db: Session, patient_id: str) -> list[OrderRead]:
    return [
        _read(x)
        for x in db.scalars(
            select(ClinicalOrder)
            .where(ClinicalOrder.patient_id == patient_id)
            .order_by(ClinicalOrder.created_at.desc(), ClinicalOrder.id)
            .limit(500)
        ).all()
    ]


def _locked(db: Session, patient_id: str, order_id: str) -> ClinicalOrder:
    record = db.scalar(
        select(ClinicalOrder)
        .where(ClinicalOrder.id == order_id, ClinicalOrder.patient_id == patient_id)
        .with_for_update()
    )
    if record is None:
        raise HTTPException(404, detail="Назначение не найдено")
    return record


def _required_text(record: ClinicalOrder, keys: tuple[str, ...]) -> list[str]:
    return [
        name
        for name in keys
        if not isinstance(getattr(record, name), str) or not getattr(record, name).strip()
    ]


def _check_ready(record: ClinicalOrder) -> None:
    # UI-5: неизменяемые учебные кандидаты намеренно содержат ошибки.
    # Даже при заполнении всех полей они не могут стать назначением пациенту.
    if (record.source_reference or "").startswith("synthetic:ui5:v1:candidate:"):
        raise HTTPException(
            422,
            detail=(
                "Учебный проект назначения UI-5 запрещено утверждать. "
                "Создайте отдельное проверенное назначение."
            ),
        )
    missing = _required_text(record, ("name", "indication", "rationale"))
    if record.kind == "medication":
        missing.extend(
            _required_text(
                record,
                (
                    "active_ingredient",
                    "dosage_form",
                    "strength",
                    "dose_unit",
                    "route",
                    "timezone",
                ),
            )
        )
        for key in ("dose_value", "frequency_per_day", "start_date", "duration_days"):
            if getattr(record, key) is None:
                missing.append(key)
        times = record.times_local or []
        if record.frequency_per_day is None or len(times) != record.frequency_per_day:
            missing.append("times_local")
    elif record.kind == "examination":
        missing.extend(_required_text(record, ("examination_details",)))
    else:
        raise HTTPException(422, detail="Неизвестный вид назначения")
    if missing:
        raise HTTPException(
            422,
            detail=(
                "Нельзя утверждать неполное назначение. Поля: " + ", ".join(sorted(set(missing)))
            ),
        )
    # Дополнительная независимая проверка типов БД перед утверждением.
    fields = {name: getattr(record, name) for name in OrderDraftCreate.model_fields}
    fields["request_key"] = UUID(fields["request_key"])
    OrderDraftCreate.model_validate(fields)


def update(
    db: Session, patient_id: str, order_id: str, actor_id: str, payload: OrderUpdate
) -> OrderRead:
    record = _locked(db, patient_id, order_id)
    if record.status != "draft" or record.version != payload.expected_version:
        raise HTTPException(409, detail="Изменился статус или версия черновика")
    if record.author_id != actor_id:
        raise HTTPException(403, detail="Редактировать может автор черновика")
    if payload.data.kind != record.kind or str(payload.data.request_key) != record.request_key:
        raise HTTPException(409, detail="Тип и ключ черновика изменить нельзя")
    for field, value in payload.data.model_dump(exclude={"kind", "request_key"}).items():
        setattr(record, field, value)
    record.version += 1
    _audit(db, record, actor_id, "draft_updated")
    db.commit()
    return _read(record)


def approve(
    db: Session, patient_id: str, order_id: str, actor_id: str, payload: OrderApprove
) -> OrderRead:
    record = _locked(db, patient_id, order_id)
    if record.version != payload.expected_version or record.status != "draft":
        raise HTTPException(409, detail="Статус или версия изменились. Обновите карточку")
    _check_ready(record)
    record.status = "approved"
    record.version += 1
    record.approved_by_id = actor_id
    record.approved_at = utc_now()
    _audit(db, record, actor_id, "approved")
    db.commit()
    return _read(record)


def cancel(
    db: Session, patient_id: str, order_id: str, actor_id: str, payload: OrderCancel
) -> OrderRead:
    record = _locked(db, patient_id, order_id)
    if record.version != payload.expected_version or record.status == "cancelled":
        raise HTTPException(409, detail="Статус или версия изменились. Обновите карточку")
    record.status = "cancelled"
    record.version += 1
    record.cancelled_at = utc_now()
    record.cancelled_by_id = actor_id
    record.cancel_reason = payload.reason
    _audit(db, record, actor_id, "cancelled")
    db.commit()
    return _read(record)


def patient_list(db: Session, user_id: str) -> PatientOrdersList:
    patient_id = db.scalar(
        select(Patient.id).where(Patient.user_id == user_id, Patient.deleted_at.is_(None))
    )
    if patient_id is None:
        raise HTTPException(404, detail="Карточка пациента не привязана")
    records = db.scalars(
        select(ClinicalOrder)
        .where(
            ClinicalOrder.patient_id == patient_id,
            ClinicalOrder.status == "approved",
            ClinicalOrder.approved_at.is_not(None),
        )
        .order_by(ClinicalOrder.approved_at.desc(), ClinicalOrder.id)
        .limit(500)
    ).all()
    items = [PatientOrderRead.model_validate(item, from_attributes=True) for item in records]
    return PatientOrdersList(items=items, total=len(items))
