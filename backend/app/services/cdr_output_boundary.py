"""6.4.1b: приём НЕДОВЕРЕННЫХ байтов от будущего CDR-worker.

Этот модуль НЕ запускает Docker, не подтверждает санитаризацию,
не выдаёт допуск в Context Builder и не сохраняет медицинские данные.
Структурная проверка PDF — не CDR, не антивирус и не PDF-парсер.
"""

import hashlib
from dataclasses import dataclass, field
from hmac import compare_digest
from typing import BinaryIO

from app.services.attachment_cdr_boundary import CDR_INPUT_FORMATS
from app.services.attachment_storage import MAX_FILE_BYTES
from app.services.cdr_isolation_contract import UnexecutedCDRPlan

PDF_MEDIA_TYPE = "application/pdf"
MAX_CDR_OUTPUT_BYTES = MAX_FILE_BYTES
_READ_CHUNK = 64 * 1024
_ALLOWED_SOURCE_TYPES = frozenset(CDR_INPUT_FORMATS.values())


class CDROutputRejected(ValueError):
    """Невозможно принять байты даже как недоверенный CDR-артефакт."""


@dataclass(frozen=True)
class UntrustedCDROutput:
    """Снимок результата, который ОБЯЗАН остаться в карантине.

    Не передавать `content` в Context Builder, HTML или публичные API.
    Поля SHA-256 — проверка целостности, но не доказательство очистки.
    """

    source_sha256: str
    output_sha256: str
    output_length: int
    media_type: str
    content: bytes = field(repr=False)

    @property
    def sanitized(self) -> bool:
        return False

    @property
    def processing_allowed(self) -> bool:
        return False

    @property
    def trusted(self) -> bool:
        return False


def _validate_input_plan(plan: UnexecutedCDRPlan) -> None:
    """Проверяем целостность плана заново, даже если объект был изменён вручную."""
    if not isinstance(plan, UnexecutedCDRPlan):
        raise CDROutputRejected("Отсутствует исходный план CDR")
    if plan.media_type not in _ALLOWED_SOURCE_TYPES:
        raise CDROutputRejected("Формат исходника не разрешён")
    if (
        type(plan.content_length) is not int
        or not isinstance(plan.stdin_payload, bytes)
        or not 1 <= plan.content_length <= MAX_FILE_BYTES
        or len(plan.stdin_payload) != plan.content_length
    ):
        raise CDROutputRejected("Размер исходного снимка не совпадает")
    if (
        not isinstance(plan.content_sha256, str)
        or len(plan.content_sha256) != 64
        or any(c not in "0123456789abcdef" for c in plan.content_sha256)
        or not compare_digest(
            hashlib.sha256(plan.stdin_payload).hexdigest(),
            plan.content_sha256,
        )
    ):
        raise CDROutputRejected("SHA-256 исходного снимка не совпадает")


def capture_untrusted_cdr_output(
    plan: UnexecutedCDRPlan,
    output_stream: BinaryIO,
    *,
    media_type: str = PDF_MEDIA_TYPE,
) -> UntrustedCDROutput:
    """Ограниченно прочитать выход будущего CDR как ОПАСНЫЙ карантинный артефакт.

    Принимается только PDF; DOCX-вход при будущем рендеринге может дать PDF.
    Любые ошибки, подмена исходника, превышение лимита и passthrough отклоняются.
    Наличие `%PDF-` и `%%EOF` НЕ доказывает, что PDF безопасен.
    Время выполнения и доверие к worker — ответственность внешнего исполнителя.
    """
    _validate_input_plan(plan)
    if media_type != PDF_MEDIA_TYPE:
        raise CDROutputRejected("CDR-выход должен быть PDF")
    if not hasattr(output_stream, "read"):
        raise CDROutputRejected("Требуется бинарный поток")

    buffer = bytearray()
    digest = hashlib.sha256()
    try:
        while True:
            part = output_stream.read(min(_READ_CHUNK, MAX_CDR_OUTPUT_BYTES + 1 - len(buffer)))
            if not isinstance(part, bytes):
                raise CDROutputRejected("CDR вернул небинарные данные")
            if not part:
                break
            if len(buffer) + len(part) > MAX_CDR_OUTPUT_BYTES:
                raise CDROutputRejected("CDR-выход превышает лимит размера")
            buffer.extend(part)
            digest.update(part)
    except (OSError, MemoryError) as exc:
        raise CDROutputRejected("Невозможно прочитать CDR-выход") from exc

    if not buffer:
        raise CDROutputRejected("Пустой результат CDR")
    if not buffer.startswith(b"%PDF-") or b"%%EOF" not in buffer[-1024:]:
        raise CDROutputRejected("CDR-выход не похож на завершённый PDF")

    # Точное совпадение с оригиналом не считается результатом преобразования.
    output_sha256 = digest.hexdigest()
    if compare_digest(output_sha256, plan.content_sha256):
        raise CDROutputRejected("CDR вернул неизменённый оригинал")

    return UntrustedCDROutput(
        source_sha256=plan.content_sha256,
        output_sha256=output_sha256,
        output_length=len(buffer),
        media_type=PDF_MEDIA_TYPE,
        content=bytes(buffer),
    )
