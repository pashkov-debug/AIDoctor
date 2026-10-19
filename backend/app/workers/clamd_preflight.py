"""6.3.2: ручная диагностика настоящего локального clamd на EICAR.

Это НЕ аттестация происхождения демона и НЕ разрешение обработки вложений.
Не читает файлы пациента, не обращается к БД и не сохраняет тестовые данные.
"""

import argparse
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from app.services.attachment_clamd import ClamdScanner, ClamdUnavailable

_VERSION = re.compile(r"^ClamAV (\d+(?:\.\d+){1,2})/(\d{1,12})/(.+)$")


class PreflightFailure(RuntimeError):
    """Сканер недоступен, детектирование не работает или базы устарели."""


def eicar_bytes() -> bytes:
    """Безвредный отраслевой AV-тест. Собирается в памяти, не пишется на диск."""
    # Не помещаем полную сигнатуру подряд в исходник: Windows Defender может
    # принять сам исходный файл с тестовой строкой за заражённый.
    return (
        b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$"
        + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!"
        + b"$H+H*"
    )


def validate_signature_date(
    version: str,
    *,
    now: datetime | None = None,
    max_age_days: int = 7,
) -> datetime:
    """Проверить форму VERSION и заявленную дату сигнатур (не подлинность)."""
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
    # clamd VERSION обычно возвращает дату в UTC без суффикса часового пояса.
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


def verify_clamd(
    scanner: ClamdScanner,
    *,
    now: datetime | None = None,
    max_age_days: int = 7,
) -> datetime:
    """Передать только EICAR в локальный clamd; ожидать срабатывание сигнатуры."""
    try:
        result = scanner.scan(eicar_bytes())
    except (ClamdUnavailable, OSError, TimeoutError) as exc:
        raise PreflightFailure("Нет законченного ответа локального clamd") from exc
    if result.status != "infected_reported":
        raise PreflightFailure("AV не распознал тестовую EICAR-сигнатуру")
    return validate_signature_date(
        result.engine_version, now=now, max_age_days=max_age_days
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Локальный AV smoke-test 6.3.2")
    parser.add_argument(
        "--check-eicar", action="store_true", help="Разрешить тестовую INSTREAM-передачу"
    )
    parser.add_argument("--max-db-age-days", type=int, default=7)
    args = parser.parse_args(argv)
    if not args.check_eicar:
        parser.error("Требуется явный ключ --check-eicar")
    if not 1 <= args.max_db_age_days <= 30:
        parser.error("--max-db-age-days должен быть от 1 до 30")

    try:
        checked = verify_clamd(ClamdScanner(), max_age_days=args.max_db_age_days)
    except PreflightFailure as exc:
        print(f"FAIL: {exc}. Карантин сохраняется.")
        return 1
    print(
        "PASS: локальный clamd сообщил обнаружение EICAR; "
        f"заявленная дата сигнатур (UTC): {checked.isoformat()}. "
        "Это не аттестация демона и не допуск вложений."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
