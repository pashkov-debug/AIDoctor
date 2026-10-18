"""Однократная административная проверка по явной команде.

Не исполняется фоном. Не пишет в Outbox/Inbox и не доставляет сообщения.
"""

import argparse

from app.core.config import settings
from app.services.safety_followups import create_one_due_followup


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Однократная постановка просроченного сигнала в follow-up"
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)

    if not args.once:
        parser.print_help()
        return 2
    if not settings.safety_followup_scan_enabled:
        print("Follow-up отключён: SAFETY_FOLLOWUP_SCAN_ENABLED=false.")
        return 2

    from app.db.session import SessionLocal

    with SessionLocal() as session:
        result = create_one_due_followup(session)
    print(f"Административный follow-up: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
