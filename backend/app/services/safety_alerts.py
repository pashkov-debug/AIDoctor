"""Транзакции сигналов, Outbox и идемпотентных HTTP-запросов в PostgreSQL."""

import hashlib
import json
import re

from app.db.base import new_uuid, utc_now
from app.models.safety_alert import SafetyAlert, SafetyAlertEvent
from app.models.safety_alert_request import SafetyAlertRequest
from app.schemas.safety_alert import SafetyAlertCreate
from app.services.safety_outbox import enqueue_alert_created
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session


class AlertNotFoundError(Exception):
    """Сигнал отсутствует у данного пациента."""


class InvalidIdempotencyKey(ValueError):
    """Недопустимый формат ключа HTTP-запроса."""


class IdempotencyConflict(Exception):
    """Ключ уже использовался для создания сигнала с другим содержимым."""


_KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", re.ASCII)


def idempotency_key_digest(key: str) -> str:
    """Проверить ключ и вернуть SHA-256 вместо хранения его исходного значения."""
    if not isinstance(key, str) or _KEY_PATTERN.fullmatch(key) is None:
        raise InvalidIdempotencyKey(
            "Idempotency-Key: 8–128 символов ASCII, буквы/цифры/._:-"
        )
    return hashlib.sha256(b"safety-alert-key:v1:" + key.encode("ascii")).hexdigest()


def alert_request_digest(data: SafetyAlertCreate) -> str:
    """Отпечаток семантических полей текущего контракта."""
    payload = json.dumps(
        {"reason_code": data.reason_code, "priority": data.priority},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(b"safety-alert-body:v1:" + payload).hexdigest()


def _existing_alert(
    session: Session,
    patient_id: str,
    actor_id: str,
    key_digest: str,
    request_digest: str,
) -> SafetyAlert | None:
    record = session.scalar(
        select(SafetyAlertRequest).where(
            SafetyAlertRequest.patient_id == patient_id,
            SafetyAlertRequest.actor_id == actor_id,
            SafetyAlertRequest.key_digest == key_digest,
        )
    )
    if record is None:
        return None
    if record.request_digest != request_digest:
        raise IdempotencyConflict(
            "Idempotency-Key уже использован с другим содержимым запроса"
        )
    alert = session.get(SafetyAlert, record.alert_id)
    if alert is None:
        raise RuntimeError("Нарушена ссылочная целостность ключа идемпотентности")
    return alert


def list_alerts(session: Session, patient_id: str) -> list[SafetyAlert]:
    return list(
        session.scalars(
            select(SafetyAlert)
            .where(SafetyAlert.patient_id == patient_id)
            .order_by(SafetyAlert.created_at.desc(), SafetyAlert.id.desc())
            .limit(100)
        ).all()
    )


def create_alert(
    session: Session,
    patient_id: str,
    actor_id: str,
    data: SafetyAlertCreate,
    *,
    idempotency_key: str | None = None,
) -> SafetyAlert:
    """Создать сигнал+Outbox атомарно; повтор ключа возвращает тот же alert_id.

    Без заголовка поведение этапа 5.2 сохраняется. Session/commit принадлежит сервису.
    """
    key_digest = None
    request_digest = None
    if idempotency_key is not None:
        key_digest = idempotency_key_digest(idempotency_key)
        request_digest = alert_request_digest(data)

    try:
        if key_digest is not None and request_digest is not None:
            existing = _existing_alert(
                session, patient_id, actor_id, key_digest, request_digest
            )
            if existing is not None:
                return existing

        alert = SafetyAlert(
            patient_id=patient_id,
            created_by_id=actor_id,
            reason_code=data.reason_code,
            priority=data.priority,
            status="open",
        )
        session.add(alert)
        session.flush()
        session.add(
            SafetyAlertEvent(
                alert_id=alert.id, actor_id=actor_id, event_type="created"
            )
        )
        enqueue_alert_created(session, alert.id)

        if key_digest is not None and request_digest is not None:
            inserted = session.scalar(
                pg_insert(SafetyAlertRequest)
                .values(
                    id=new_uuid(),
                    created_at=utc_now(),
                    patient_id=patient_id,
                    actor_id=actor_id,
                    alert_id=alert.id,
                    key_digest=key_digest,
                    request_digest=request_digest,
                )
                .on_conflict_do_nothing(constraint="uq_safety_alert_requests_scope_key")
                .returning(SafetyAlertRequest.id)
            )
            if inserted is None:
                # Победивший конкурент уже зафиксировал запись.
                # Откатываем ВСЕ локальные изменения, включая Outbox и аудит.
                session.rollback()
                existing = _existing_alert(
                    session, patient_id, actor_id, key_digest, request_digest
                )
                if existing is None:
                    raise RuntimeError("Ключ идемпотентности не найден после конфликта")
                return existing

        session.commit()
        session.refresh(alert)
        return alert
    except Exception:
        session.rollback()
        raise


def acknowledge_alert(
    session: Session, patient_id: str, alert_id: str, actor_id: str
) -> SafetyAlert:
    alert = session.scalar(
        select(SafetyAlert).where(
            SafetyAlert.id == alert_id, SafetyAlert.patient_id == patient_id
        )
    )
    if alert is None:
        raise AlertNotFoundError

    if alert.status == "acknowledged":
        return alert

    try:
        acknowledged_id = session.scalar(
            update(SafetyAlert)
            .where(
                SafetyAlert.id == alert_id,
                SafetyAlert.patient_id == patient_id,
                SafetyAlert.status == "open",
            )
            .values(
                status="acknowledged",
                acknowledged_by_id=actor_id,
                acknowledged_at=utc_now(),
            )
            .returning(SafetyAlert.id)
        )
        if acknowledged_id is not None:
            session.add(
                SafetyAlertEvent(
                    alert_id=alert_id, actor_id=actor_id, event_type="acknowledged"
                )
            )
        session.commit()
        refreshed = session.get(SafetyAlert, alert_id)
        if refreshed is None:
            raise AlertNotFoundError
        return refreshed
    except Exception:
        session.rollback()
        raise
