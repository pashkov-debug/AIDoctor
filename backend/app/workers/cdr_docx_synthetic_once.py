"""Ручной synthetic-only smoke-test DOCX CDR, по умолчанию ничего не запускает."""

import argparse

from app.services.cdr_docx_synthetic_execution import run_synthetic_docx_cdr
from app.services.cdr_synthetic_execution import CDRExecutionDenied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Только синтетический DOCX CDR")
    parser.add_argument("--run-synthetic", action="store_true")
    parser.add_argument("--image-id", required=True, help="Локальный sha256 ID образа")
    args = parser.parse_args(argv)
    if not args.run_synthetic:
        parser.error("Нужно явно указать --run-synthetic")
    try:
        result = run_synthetic_docx_cdr(image_id=args.image_id)
    except CDRExecutionDenied:
        print("FAIL: синтетический DOCX CDR не прошёл проверку")
        return 1
    print(
        f"PASS: синтетический DOCX преобразован в растровый PDF; "
        f"SHA-256={result.output_sha256}; байт={result.output_length}; "
        "обработка медицинских вложений ЗАПРЕЩЕНА"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
