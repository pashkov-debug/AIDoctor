"""Ручное сканирование с обязательным EICAR-гейтом без снятия карантина.

Запуск: python -m app.workers.attachment_clamd_once --once --patient-id UUID
        --attachment-id UUID --actor-id UUID
"""

import argparse

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.attachment_av_policy import PreflightGatedScanner
from app.services.attachment_av_scan import scan_quarantined_attachment
from app.services.attachment_clamd import ClamdScanner
from app.services.attachment_storage import AttachmentStorage


def main() -> int:
    parser = argparse.ArgumentParser(description="Одно локальное AV-сканирование")
    parser.add_argument("--once", action="store_true", help="Подтверждение единичного запуска")
    parser.add_argument("--patient-id", required=True)
    parser.add_argument("--attachment-id", required=True)
    parser.add_argument("--actor-id", required=True, help="UUID действующего администратора")
    args = parser.parse_args()

    if not args.once or not settings.attachment_clamd_enabled:
        parser.error("Требуются --once и ATTACHMENT_CLAMD_ENABLED=true")
    try:
        with SessionLocal() as session:
            record = scan_quarantined_attachment(
                session,
                patient_id=args.patient_id,
                attachment_id=args.attachment_id,
                actor_id=args.actor_id,
                storage=AttachmentStorage(settings.attachments_dir),
                scanner=PreflightGatedScanner(ClamdScanner()),
            )
    except Exception:
        # Не выводим системные пути, имена файлов, токены или содержимое.
        print("AV-операция не завершена; карантин сохраняется")
        return 1
    print(f"AV-отчёт: {record.status}; ID={record.id}; карантин сохранён")
    return 0 if record.status != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
