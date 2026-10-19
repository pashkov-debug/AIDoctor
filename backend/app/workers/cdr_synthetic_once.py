"""Ручной smoke-test 6.4.2. Запускает CDR только на встроенном PDF.

Пример:
  python -m app.workers.cdr_synthetic_once --run-synthetic --image-id sha256:...
"""

import argparse

from app.services.cdr_synthetic_execution import (
    CDRExecutionDenied,
    run_synthetic_pdf_cdr,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Синтетический PDF CDR smoke-test")
    parser.add_argument("--run-synthetic", action="store_true")
    parser.add_argument("--image-id", required=True, help="Локальный sha256 image ID")
    args = parser.parse_args(argv)
    if not args.run_synthetic:
        parser.error("Для запуска требуется --run-synthetic")
    try:
        result = run_synthetic_pdf_cdr(image_id=args.image_id)
    except CDRExecutionDenied:
        print("FAIL: CDR-контейнер или его результат не прошёл проверку")
        return 1
    print(
        f"PASS: синтетический PDF перестроен; SHA-256={result.output_sha256}; "
        f"байт={result.output_length}; обработка медицинских вложений ЗАПРЕЩЕНА"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
