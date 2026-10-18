"""Транзакционный Outbox: доставка не запускается, методы предназначены для будущего worker."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.db.base import new_uuid, utc_now
from app.models.safety_outbox import SafetyOutbox, SafetyOutboxEvent
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

MAX_ATTEMPTS = 3
RETRY_BASE_SECONDS = 30
RETRY_CAP_SECONDS = 3600


@dataclass(frozen=True)
class OutboxClaim:
    outbox_id: str
    alert_id: str
    event_type: str
    token: str
    attempt_number: int


class InvalidOutboxClaim(Exception):
    """Попытка завершить несуществующее, устаревшее или просроченное резервирование."""


def retry_delay_seconds(attempt_number: int) -> int:
    """Пауза после неудачной попытки; третья попытка окончательная."""
    if not 1 <= attempt_number <= MAX_ATTEMPTS:
        raise ValueError("Недопустимый номер попытки")
    return min(RETRY_BASE_SECONDS * (2 ** (attempt_number - 1)), RETRY_CAP_SECONDS)


def _now_or_raise(now: datetime | None) -> datetime:
    result = now if now is not None else utc_now()
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Время должно содержать часовой пояс")
    return result.astimezone(UTC)


def enqueue_alert_created(session: Session, alert_id: str) -> str:
    """Идемпотентно создать запись по alert_id; без commit — транзакцией владеет caller."""
    now = utc_now()
    new_id = session.scalar(
        pg_insert(SafetyOutbox)
        .values(
            id=new_uuid(),
            created_at=now,
            alert_id=alert_id,
            event_type="created",
            status="pending",
            attempt_count=0,
            next_attempt_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_safety_outbox_source_event")
        .returning(SafetyOutbox.id)
    )
    if new_id is not None:
        session.add(
            SafetyOutboxEvent(
                outbox_id=new_id,
                event_type="enqueued",
                attempt_number=0,
            )
        )
        return new_id
    existing_id = session.scalar(
        select(SafetyOutbox.id).where(
            SafetyOutbox.alert_id == alert_id,
            SafetyOutbox.event_type == "created",
        )
    )
    if existing_id is None:
        raise RuntimeError("Конфликт идемпотентности Outbox без существующей записи")
    return existing_id


def _record(
    session: Session,
    item: SafetyOutbox,
    event_type: str,
    error_code: str | None = None,
) -> None:
    session.add(
        SafetyOutboxEvent(
            outbox_id=item.id,
            event_type=event_type,
            attempt_number=item.attempt_count,
            error_code=error_code,
        )
    )


def _failed_attempt(
    session: Session, item: SafetyOutbox, now: datetime, error_code: str
) -> None:
    item.claim_token = None
    item.lease_expires_at = None
    item.last_error_code = error_code
    if item.attempt_count >= MAX_ATTEMPTS:
        item.status = "failed"
        _record(session, item, "exhausted", error_code)
    else:
        item.status = "pending"
        item.next_attempt_at = now + timedelta(seconds=retry_delay_seconds(item.attempt_count))
        _record(session, item, "retry_scheduled", error_code)


def _recover_expired(session: Session, now: datetime, limit: int = 100) -> None:
    """Вернуть истёкшие leases в очередь либо исчерпать лимит попыток."""
    expired = session.scalars(
        select(SafetyOutbox)
        .where(
            SafetyOutbox.status == "processing",
            SafetyOutbox.lease_expires_at <= now,
        )
        .order_by(SafetyOutbox.lease_expires_at, SafetyOutbox.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for item in expired:
        _failed_attempt(session, item, now, "lease_expired")
    session.flush()


def claim_due(
    session: Session,
    *,
    limit: int = 10,
    lease_seconds: int = 300,
    now: datetime | None = None,
) -> list[OutboxClaim]:
    """Зарезервировать ожидающие записи атомарно, без сетевых вызовов."""
    if not 1 <= limit <= 100 or not 30 <= lease_seconds <= 3600:
        raise ValueError("Недопустимые limit или lease_seconds")
    moment = _now_or_raise(now)
    try:
        _recover_expired(session, moment)
        items = session.scalars(
            select(SafetyOutbox)
            .where(
                SafetyOutbox.status == "pending",
                SafetyOutbox.attempt_count < MAX_ATTEMPTS,
                SafetyOutbox.next_attempt_at <= moment,
            )
            .order_by(SafetyOutbox.next_attempt_at, SafetyOutbox.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        claims: list[OutboxClaim] = []
        for item in items:
            item.status = "processing"
            item.attempt_count += 1
            item.claim_token = new_uuid()
            item.lease_expires_at = moment + timedelta(seconds=lease_seconds)
            _record(session, item, "claimed")
            claims.append(
                OutboxClaim(
                    outbox_id=item.id,
                    alert_id=item.alert_id,
                    event_type=item.event_type,
                    token=item.claim_token,
                    attempt_number=item.attempt_count,
                )
            )
        session.commit()
        return claims
    except Exception:
        session.rollback()
        raise


def _locked_claim(
    session: Session, claim: OutboxClaim, now: datetime
) -> SafetyOutbox:
    item = session.scalar(
        select(SafetyOutbox)
        .where(SafetyOutbox.id == claim.outbox_id)
        .with_for_update()
    )
    if (
        item is None
        or item.status != "processing"
        or item.claim_token != claim.token
        or item.lease_expires_at is None
        or item.lease_expires_at <= now
        or item.attempt_count != claim.attempt_number
        or item.alert_id != claim.alert_id
        or item.event_type != claim.event_type
    ):
        raise InvalidOutboxClaim
    return item


def mark_delivered(
    session: Session, claim: OutboxClaim, *, now: datetime | None = None
) -> None:
    """Только после подтверждения реальной доставки будущим адаптером."""
    moment = _now_or_raise(now)
    try:
        item = _locked_claim(session, claim, moment)
        item.status = "delivered"
        item.claim_token = None
        item.lease_expires_at = None
        item.last_error_code = None
        item.delivered_at = moment
        _record(session, item, "delivered")
        session.commit()
    except Exception:
        session.rollback()
        raise


def mark_attempt_failed(
    session: Session,
    claim: OutboxClaim,
    *,
    error_code: str,
    now: datetime | None = None,
) -> None:
    """Сохранить категорию ошибки, но не исключение/PII/текст сообщения."""
    if not isinstance(error_code, str) or re.fullmatch(r"[a-z][a-z0-9_]{1,47}", error_code) is None:
        raise ValueError("error_code: только латиница, цифры и '_' (2–48 символов)")
    moment = _now_or_raise(now)
    try:
        item = _locked_claim(session, claim, moment)
        _failed_attempt(session, item, moment, error_code)
        session.commit()
    except Exception:
        session.rollback()
        raise
