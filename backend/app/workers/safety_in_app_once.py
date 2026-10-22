"""Одна локальная доставка при явном разрешении; без автоматического цикла.

Включается одновременно настройкой SAFETY_IN_APP_DELIVERY_ENABLED=true
и аргументом --once. Не использует email, SMS, push или сторонние API.
"""

import argparse

from app.core.config import settings
from app.services.safety_in_app_delivery import InAppTransport
from app.workers.safety_outbox import process_one


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safety Outbox → локальный in_app inbox")
    parser.add_argument("--once", action="store_true", help="Обработать одну запись Outbox")
    args = parser.parse_args(argv)
    if not args.once:
        parser.print_help()
        return 2
    if not settings.safety_in_app_delivery_enabled:
        print("Доставка отключена: SAFETY_IN_APP_DELIVERY_ENABLED=false.")
        return 2

    from app.db.session import SessionLocal

    result = process_one(SessionLocal, InAppTransport(SessionLocal, enabled=True))
    print(f"Результат локального inbox: {result}")
    return 0 if result in {"empty", "delivered"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
