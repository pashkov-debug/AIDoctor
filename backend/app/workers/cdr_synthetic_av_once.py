"""6.5.0: ручной повторный AV после синтетического CDR, без файлов пациентов.

Пример:
  python -m app.workers.cdr_synthetic_av_once --once --pdf-image-id sha256:...
"""

import argparse

from app.core.config import settings
from app.services.attachment_av_policy import PreflightGatedScanner
from app.services.attachment_clamd import ClamdScanner
from app.services.cdr_docx_synthetic_execution import run_synthetic_docx_cdr
from app.services.cdr_synthetic_execution import (
    CDRExecutionDenied,
    run_synthetic_pdf_cdr,
)
from app.services.cdr_synthetic_output_av import (
    CDRRepeatAVDenied,
    scan_synthetic_cdr_output,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Повторный AV для встроенного синтетического CDR-примера"
    )
    parser.add_argument("--once", action="store_true", help="Явный единичный запуск")
    image = parser.add_mutually_exclusive_group(required=True)
    image.add_argument("--pdf-image-id", help="Локальный sha256 ID PDF CDR-образа")
    image.add_argument("--docx-image-id", help="Локальный sha256 ID DOCX CDR-образа")
    args = parser.parse_args(argv)

    if not args.once or not settings.attachment_clamd_enabled:
        parser.error("Нужны --once и ATTACHMENT_CLAMD_ENABLED=true")

    try:
        if args.pdf_image_id:
            converted = run_synthetic_pdf_cdr(image_id=args.pdf_image_id)
        else:
            converted = run_synthetic_docx_cdr(image_id=args.docx_image_id)
        receipt = scan_synthetic_cdr_output(
            converted,
            scanner=PreflightGatedScanner(ClamdScanner()),
        )
    except (CDRExecutionDenied, CDRRepeatAVDenied):
        print("FAIL: синтетический CDR или повторная AV-проверка отклонены")
        return 1

    # В выводе только технические хеши; не записываем тело PDF/имена.
    print(
        f"CDR AV: {receipt.status}; SHA-256={receipt.output_sha256}; "
        f"байт={receipt.output_length}; карантин и запрет обработки сохранены"
    )
    return 0 if receipt.status == "clean_reported" else 1


if __name__ == "__main__":
    raise SystemExit(main())
