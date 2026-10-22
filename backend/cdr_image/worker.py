#!/usr/bin/env python3
"""Одноразовый PDF→JPEG страниц→PDF worker в изолированном Docker.

Вход: PDF на stdin; выход: новый PDF на stdout. Ошибки только generic exit 1.
Содержимое/метаданные пациента никогда не печатаются в stderr.
Без сетевых вызовов, OCR, чтения клинических файлов и доступа к БД.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 8
_COMMAND_TIMEOUT = 30


class ConversionDenied(Exception):
    """Формат, ограничения либо исполняемый движок отклонили вход."""


def _run(args: list[str]) -> bytes:
    try:
        completed = subprocess.run(
            args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=_COMMAND_TIMEOUT,
            shell=False,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise ConversionDenied("Ошибка утилиты рендеринга") from exc
    if len(completed.stdout) > 65536:
        raise ConversionDenied("Слишком большой служебный вывод")
    return completed.stdout


def _pdf_page_count(source: Path) -> int:
    info = _run(["pdfinfo", str(source)])
    # pdfinfo выводит также метаданные PDF: мы их не логируем.
    encryption = re.search(rb"(?im)^Encrypted:\s*(yes|no)(?:\s|$)", info)
    if not encryption or encryption.group(1).lower() != b"no":
        raise ConversionDenied("Зашифрованный PDF или нет явного статуса")
    match = re.search(rb"(?m)^Pages:\s*([0-9]+)\s*$", info)
    if not match:
        raise ConversionDenied("Невозможно проверить число страниц")
    pages = int(match.group(1))
    if pages < 1 or pages > MAX_PAGES:
        raise ConversionDenied("Слишком много страниц")
    return pages


def convert_pdf(payload: bytes) -> bytes:
    if (
        not isinstance(payload, bytes)
        or not 0 < len(payload) <= MAX_BYTES
        or not payload.startswith(b"%PDF-")
    ):
        raise ConversionDenied("Только ограниченный PDF")
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="cdr-") as directory:
        tmp = Path(directory)
        source = tmp / "input.pdf"
        source.write_bytes(payload)
        pages = _pdf_page_count(source)
        prefix = tmp / "page"
        _run(
            [
                "pdftoppm",
                "-jpeg",
                "-jpegopt",
                "quality=75",
                "-r",
                "96",
                "-f",
                "1",
                "-l",
                str(pages),
                str(source),
                str(prefix),
            ]
        )
        files = sorted(
            tmp.glob("page-*.jpg"),
            key=lambda item: int(item.stem.rsplit("-", 1)[-1]),
        )
        if len(files) != pages:
            raise ConversionDenied("Недостаточное число растеризованных страниц")
        for file in files:
            if file.stat().st_size == 0 or file.stat().st_size > MAX_BYTES:
                raise ConversionDenied("Слишком большой результат рендеринга")
            with file.open("rb") as handle:
                if handle.read(3) != b"\xff\xd8\xff":
                    raise ConversionDenied("Некорректное изображение страницы")
        output = tmp / "result.pdf"
        _run(["img2pdf", "--output", str(output), *map(str, files)])
        if not output.is_file() or not 0 < output.stat().st_size <= MAX_BYTES:
            raise ConversionDenied("Некорректный размер выходного PDF")
        with output.open("rb") as handle:
            result = handle.read(MAX_BYTES + 1)
        if not result.startswith(b"%PDF-") or b"%%EOF" not in result[-1024:]:
            raise ConversionDenied("Неполный PDF")
        return result


def main() -> int:
    try:
        payload = sys.stdin.buffer.read(MAX_BYTES + 1)
        result = convert_pdf(payload)
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()
    except (ConversionDenied, OSError, MemoryError, ValueError, OverflowError):
        print("CDR отклонил документ", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
