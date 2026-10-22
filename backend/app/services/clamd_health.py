"""Проверка состояния локального clamd: EICAR + заявленная свежесть баз.

Ни EICAR, ни VERSION не удостоверяют подлинность TCP-демона.
Результат никогда не является разрешением обрабатывать вложения.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from app.services.attachment_clamd import ClamdScanner, ClamdUnavailable

_VERSION = re.compile(r"^ClamAV (\d+(?:\.\d+){1,2})/(\d{1,12})/(.+)$")


class PreflightFailure(RuntimeError):
    """Сканер недоступен, EICAR не обнаружен либо базы устарели."""


@dataclass(frozen=True)
class ClamdHealth:
    signature_date: datetime
    engine_version: str


def eicar_bytes() -> bytes:
    """Безвредный тест: строится в памяти, не записывается на диск."""
    return b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$" + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!" + b"$H+H*"


def validate_signature_date(
    version: str,
    *,
    now: datetime | None = None,
    max_age_days: int = 7,
) -> datetime:
    """Дата из VERSION — заявление демона, не криптографическое доказательство."""
    if not isinstance(version, str):
        raise PreflightFailure("Некорректная версия clamd")
    if not 1 <= max_age_days <= 30:
        raise ValueError("Допустимый возраст базы: 1–30 дней")
    match = _VERSION.fullmatch(version)
    if match is None or int(match.group(2)) == 0:
        raise PreflightFailure("VERSION не содержит номер и дату базы")
    try:
        dt = parsedate_to_datetime(match.group(3))
    except (TypeError, ValueError, IndexError) as exc:
        raise PreflightFailure("Дата сигнатур не распознана") from exc
    if dt is None:
        raise PreflightFailure("Дата сигнатур не распознана")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    else:
        dt = dt.astimezone(UTC)

    current = datetime.now(UTC) if now is None else now
    if current.tzinfo is None:
        raise ValueError("now должен быть timezone-aware")
    current = current.astimezone(UTC)
    if dt > current + timedelta(hours=24):
        raise PreflightFailure("Дата базы находится в будущем: проверить часы")
    if current - dt > timedelta(days=max_age_days):
        raise PreflightFailure("База ClamAV устарела")
    return dt


def verify_clamd_with_version(
    scanner: ClamdScanner,
    *,
    now: datetime | None = None,
    max_age_days: int = 7,
) -> ClamdHealth:
    """Проверка EICAR и VERSION через тот же экземпляр транспорта."""
    try:
        result = scanner.scan(eicar_bytes())
    except (ClamdUnavailable, OSError, TimeoutError) as exc:
        raise PreflightFailure("Нет законченного ответа локального clamd") from exc
    if result.status != "infected_reported":
        raise PreflightFailure("AV не распознал тестовую EICAR-сигнатуру")
    return ClamdHealth(
        signature_date=validate_signature_date(
            result.engine_version, now=now, max_age_days=max_age_days
        ),
        engine_version=result.engine_version,
    )


def verify_clamd(
    scanner: ClamdScanner,
    *,
    now: datetime | None = None,
    max_age_days: int = 7,
) -> datetime:
    """Совместимый контракт диагностической команды 6.3.2."""
    return verify_clamd_with_version(scanner, now=now, max_age_days=max_age_days).signature_date
