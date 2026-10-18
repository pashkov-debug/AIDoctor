"""Однократное исполнение Outbox с явным транспортом; без встроенной отправки.

CLI разрешает только чтение агрегированных счётчиков. Транспорт
предоставляется вызывающим кодом после отдельной настройки и аудита.
"""

import argparse
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.safety_outbox import SafetyOutbox
from app.services.safety_outbox import (
    MAX_ATTEMPTS,
    InvalidOutboxClaim,
    OutboxClaim,
    claim_due,
    mark_attempt_failed,
    mark_delivered,
)

_RECEIPT_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,127}", re.ASCII)
_ERROR_CODES = frozenset(
    {"provider_unavailable", "provider_timeout", "provider_rejected", "route_unavailable"}
)
_STATES = ("pending", "processing", "delivered", "failed")

SessionFactory = Callable[[], Session]
WorkerOutcome = Literal["empty", "delivered", "retry_scheduled", "failed", "stale"]


@dataclass(frozen=True)
class DeliveryEnvelope:
    """Только технические идентификаторы: без пациента, медицинских фактов и адреса."""

    outbox_id: str
    alert_id: str
    event_type: str
    attempt_number: int

    @classmethod
    def from_claim(cls, claim: OutboxClaim) -> "DeliveryEnvelope":
        return cls(
            outbox_id=claim.outbox_id,
            alert_id=claim.alert_id,
            event_type=claim.event_type,
            attempt_number=claim.attempt_number,
        )


@dataclass(frozen=True)
class DeliveryReceipt:
    """Подтверждение от адаптера реального канала (не доказательство прочтения)."""

    confirmation_id: str


class DeliveryTransport(Protocol):
    """Контракт будущего транспорта; здесь нет SMTP/SMS/push/сетевых клиентов."""

    def send(self, envelope: DeliveryEnvelope) -> DeliveryReceipt:
        """Отправить событие и вернуть проверенное подтверждение."""


class TransportNotConfigured(RuntimeError):
    """Перед вызовом Outbox необходимо явно предоставить транспорт."""


class TransportFailure(Exception):
    """Известная неудача без утечки ответа провайдера или медицинских данных."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("Недопустимая категория сбоя транспорта")
        super().__init__(code)
        self.code = code


def _receipt_confirmed(value: object) -> bool:
    return (
        isinstance(value, DeliveryReceipt)
        and isinstance(value.confirmation_id, str)
        and _RECEIPT_PATTERN.fullmatch(value.confirmation_id) is not None
    )


def process_one(
    session_factory: SessionFactory,
    transport: DeliveryTransport | None,
    *,
    lease_seconds: int = 300,
) -> WorkerOutcome:
    """Одна запись и три независимые Session: claim → transport → finalization.

    Нет транспорта — нет резервирования и изменения базы. Сетевые вызовы
    выполняются только ПОСЛЕ commit claim и без удержания DB-блокировки.
    Предполагается, что транспорт ограничивает время выполнения меньше lease.
    """
    if transport is None:
        raise TransportNotConfigured("Транспорт не настроен; очередь не изменена")
    if not 30 <= lease_seconds <= 3600:
        raise ValueError("lease_seconds должен быть от 30 до 3600")

    with session_factory() as session:
        claimed = claim_due(session, limit=1, lease_seconds=lease_seconds)
    if not claimed:
        return "empty"

    claim = claimed[0]
    try:
        receipt = transport.send(DeliveryEnvelope.from_claim(claim))
    except TransportFailure as exc:
        error_code = exc.code
    except Exception:
        # Не пишем str(exc): в исключении могут быть персональные данные/секреты.
        error_code = "transport_unexpected"
    else:
        error_code = None if _receipt_confirmed(receipt) else "unconfirmed_delivery"

    try:
        with session_factory() as session:
            if error_code is None:
                mark_delivered(session, claim)
                return "delivered"
            mark_attempt_failed(session, claim, error_code=error_code)
            return "failed" if claim.attempt_number >= MAX_ATTEMPTS else "retry_scheduled"
    except InvalidOutboxClaim:
        # Lease мог истечь в момент внешнего вызова: новый worker имеет приоритет.
        # Нельзя подтверждать старый claim, даже при положительном ответе провайдера.
        return "stale"


def get_status_counts(session: Session) -> dict[str, int]:
    """Чтение только агрегатов без идентификаторов, адресов и медданных."""
    result = dict.fromkeys(_STATES, 0)
    rows = session.execute(
        select(SafetyOutbox.status, func.count()).group_by(SafetyOutbox.status)
    )
    for status, count in rows:
        if status in result:
            result[status] = count
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Диагностика Safety Outbox (отправка отключена)"
    )
    parser.add_argument(
        "--status", action="store_true", help="Только агрегаты PostgreSQL, без claim"
    )
    args = parser.parse_args(argv)
    if not args.status:
        parser.print_help()
        return 2

    # Импорт конфигурации/драйвера только при явном запуске CLI,
    # чтобы unit-тесты worker не требовали подключения к PostgreSQL.
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        counts = get_status_counts(session)
    for state in _STATES:
        print(f"{state}: {counts[state]}")
    print("Отправка отключена. Outbox не изменён.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
