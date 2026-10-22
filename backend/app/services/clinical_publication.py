"""Переходы статусов публикации, атомарный аудит, безопасная видимость пациенту."""

import hashlib

from app.db.base import utc_now
from app.models.clinical_publication import ClinicalPublication, ClinicalPublicationAudit
from app.models.history_event import HistoryEvent
from app.models.patient import Patient
from app.schemas.clinical_publication import (
    ClinicalPublicationRead,
    PatientPublicationRead,
    PatientPublicationsList,
    PublishRequest,
    RevokeRequest,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def _active_source(db: Session, patient_id: str, event_id: str) -> HistoryEvent:
    event = db.get(HistoryEvent, event_id)
    if event is None or event.patient_id != patient_id:
        raise HTTPException(404, detail="Событие пациента не найдено")
    superseded = db.scalar(
        select(HistoryEvent.id).where(
            HistoryEvent.patient_id == patient_id,
            HistoryEvent.supersedes_id == event.id,
        )
    )
    if superseded is not None:
        raise HTTPException(409, detail="Событие исправлено: сначала проверьте новую версию")
    return event


def _read(record: ClinicalPublication) -> ClinicalPublicationRead:
    return ClinicalPublicationRead(
        id=record.id,
        patient_id=record.patient_id,
        history_event_id=record.history_event_id,
        status=record.status,
        version=record.version,
        confirmed_by_id=record.confirmed_by_id,
        confirmed_at=record.confirmed_at,
        patient_text=record.patient_text,
        published_at=record.published_at,
        revoked_at=record.revoked_at,
        revoke_reason=record.revoke_reason,
    )


def _audit(
    db: Session,
    record: ClinicalPublication,
    actor_id: str,
    action: str,
    details: dict | None = None,
) -> None:
    db.add(
        ClinicalPublicationAudit(
            publication_id=record.id,
            actor_id=actor_id,
            action=action,
            version=record.version,
            details_json=details or {},
        )
    )


def confirm(db: Session, patient_id: str, event_id: str, actor_id: str) -> ClinicalPublicationRead:
    """Подтвердить источник; это НЕ публикация пациенту."""
    _active_source(db, patient_id, event_id)
    if (
        db.scalar(
            select(ClinicalPublication.id).where(ClinicalPublication.history_event_id == event_id)
        )
        is not None
    ):
        raise HTTPException(409, detail="Запись уже рассмотрена")
    record = ClinicalPublication(
        patient_id=patient_id,
        history_event_id=event_id,
        confirmed_by_id=actor_id,
        confirmed_at=utc_now(),
        status="confirmed",
        version=1,
    )
    db.add(record)
    try:
        db.flush()
        _audit(db, record, actor_id, "confirmed")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, detail="Запись уже рассмотрена") from exc
    except Exception:
        db.rollback()
        raise
    return _read(record)


def list_for_doctor(db: Session, patient_id: str) -> list[ClinicalPublicationRead]:
    records = db.scalars(
        select(ClinicalPublication)
        .where(ClinicalPublication.patient_id == patient_id)
        .order_by(ClinicalPublication.created_at.desc(), ClinicalPublication.id)
        .limit(500)
    ).all()
    return [_read(record) for record in records]


def publish(
    db: Session, patient_id: str, record_id: str, actor_id: str, data: PublishRequest
) -> ClinicalPublicationRead:
    record = db.scalar(
        select(ClinicalPublication)
        .where(
            ClinicalPublication.id == record_id,
            ClinicalPublication.patient_id == patient_id,
        )
        .with_for_update()
    )
    if record is None:
        raise HTTPException(404, detail="Запись для публикации не найдена")
    if record.version != data.expected_version:
        raise HTTPException(409, detail="Версия записи изменилась. Обновите карточку")
    if record.status != "confirmed":
        raise HTTPException(409, detail="Публикация допустима только после подтверждения")
    _active_source(db, patient_id, record.history_event_id)
    public_text = data.patient_text.strip()
    if not public_text:
        raise HTTPException(422, detail="Текст для пациента не должен быть пустым")
    record.patient_text = public_text
    record.published_at = utc_now()
    record.status = "published"
    record.version += 1
    _audit(
        db,
        record,
        actor_id,
        "published",
        {
            "text_sha256": hashlib.sha256(public_text.encode("utf-8")).hexdigest(),
            "length": len(public_text),
        },
    )
    db.commit()
    return _read(record)


def revoke(
    db: Session, patient_id: str, record_id: str, actor_id: str, data: RevokeRequest
) -> ClinicalPublicationRead:
    record = db.scalar(
        select(ClinicalPublication)
        .where(
            ClinicalPublication.id == record_id,
            ClinicalPublication.patient_id == patient_id,
        )
        .with_for_update()
    )
    if record is None:
        raise HTTPException(404, detail="Публикация не найдена")
    if record.version != data.expected_version:
        raise HTTPException(409, detail="Версия записи изменилась. Обновите карточку")
    if record.status != "published":
        raise HTTPException(409, detail="Отозвать можно только опубликованную запись")
    reason = data.reason.strip()
    if len(reason) < 3:
        raise HTTPException(422, detail="Укажите причину отзыва")
    record.status = "revoked"
    record.version += 1
    record.revoked_at = utc_now()
    record.revoked_by_id = actor_id
    record.revoke_reason = reason
    _audit(db, record, actor_id, "revoked", {"reason": reason})
    db.commit()
    return _read(record)


def list_for_patient(db: Session, user_id: str) -> PatientPublicationsList:
    patient_id = db.scalar(
        select(Patient.id).where(Patient.user_id == user_id, Patient.deleted_at.is_(None))
    )
    if patient_id is None:
        raise HTTPException(404, detail="Карточка пациента не привязана")
    # Подзапрос исключает исправленные источники, в том числе опубликованные ранее.
    superseded = select(HistoryEvent.supersedes_id).where(
        HistoryEvent.patient_id == patient_id,
        HistoryEvent.supersedes_id.is_not(None),
    )
    records = db.scalars(
        select(ClinicalPublication)
        .where(
            ClinicalPublication.patient_id == patient_id,
            ClinicalPublication.status == "published",
            ClinicalPublication.history_event_id.not_in(superseded),
        )
        .order_by(ClinicalPublication.published_at.desc(), ClinicalPublication.id)
        .limit(500)
    ).all()
    items = [
        PatientPublicationRead(id=r.id, text=r.patient_text, published_at=r.published_at)
        for r in records
        if r.patient_text and r.published_at
    ]
    return PatientPublicationsList(items=items, total=len(items))
