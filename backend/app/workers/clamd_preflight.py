"""6.3.2: ручная диагностика локального clamd без медицинских файлов.

Сама проверка не аттестует TCP-демон и никогда не снимает карантин.
"""

import argparse

from app.services.attachment_clamd import ClamdScanner
from app.services.clamd_health import (
    PreflightFailure,
    verify_clamd,
)
from app.services.clamd_health import (
    eicar_bytes as eicar_bytes,
)
from app.services.clamd_health import (
    validate_signature_date as validate_signature_date,
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
