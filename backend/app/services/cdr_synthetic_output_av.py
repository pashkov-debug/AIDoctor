"""6.5.0: повторный AV-контроль только СИНТЕТИЧЕСКОГО выхода PDF/DOCX CDR.

Не принимает произвольные файлы или медицинские вложения; не сохраняет
байты, не меняет БД и не выдаёт разрешение на клиническую обработку.
Технический отчёт в памяти НЕ является долговременным PostgreSQL-аудитом.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hmac import compare_digest

from app.services.attachment_av_policy import PreflightGatedScanner
from app.services.attachment_clamd import ClamdVerdict
from app.services.cdr_docx_synthetic_execution import (
    SyntheticDOCXResult,
    synthetic_docx,
)
from app.services.cdr_output_boundary import (
    MAX_CDR_OUTPUT_BYTES,
    PDF_MEDIA_TYPE,
    UntrustedCDROutput,
)
from app.services.cdr_synthetic_execution import SyntheticCDRResult, synthetic_pdf

_HASH = re.compile(r"[0-9a-f]{64}\Z")


class CDRRepeatAVDenied(ValueError):
    """Некорректный или неподтверждённый даже структурно выход CDR."""


@dataclass(frozen=True)
class SyntheticCDRAVReceipt:
    """Временная мета-квитанция без контента и разрешения на обработку."""

    source_sha256: str
    output_sha256: str
    output_length: int
    status: str
    reason_code: str | None
    engine_version: str | None
    checked_at: datetime

    @property
    def trusted(self) -> bool:
        return False

    @property
    def sanitized(self) -> bool:
        return False

    @property
    def processing_allowed(self) -> bool:
        return False


def _validate_synthetic_result(
    result: SyntheticCDRResult | SyntheticDOCXResult,
) -> UntrustedCDROutput:
    """Валидация метаданных и повторное хеширование фиксированного payload."""
    if not isinstance(result, (SyntheticCDRResult, SyntheticDOCXResult)):
        raise CDRRepeatAVDenied("Допускается только синтетический результат CDR")

    output = result.output
    if not isinstance(output, UntrustedCDROutput):
        raise CDRRepeatAVDenied("Нет структурного CDR-результата")
    if (
        not isinstance(output.content, bytes)
        or type(output.output_length) is not int
        or not 1 <= output.output_length <= MAX_CDR_OUTPUT_BYTES
        or len(output.content) != output.output_length
        or type(result.output_length) is not int
        or result.output_length != output.output_length
        or output.media_type != PDF_MEDIA_TYPE
    ):
        raise CDRRepeatAVDenied("Размер или формат CDR-результата изменён")

    values = (
        output.source_sha256,
        output.output_sha256,
        result.source_sha256,
        result.output_sha256,
    )
    if any(not isinstance(value, str) or _HASH.fullmatch(value) is None for value in values):
        raise CDRRepeatAVDenied("Некорректный SHA-256 CDR-результата")
    # Привязка к ВСТРОЕННОМУ примеру исключает чужие/медицинские байты
    # при создании вручную объекта с произвольным source_sha256.
    synthetic_input = (
        synthetic_pdf() if isinstance(result, SyntheticCDRResult) else synthetic_docx()
    )
    if (
        not compare_digest(output.source_sha256, hashlib.sha256(synthetic_input).hexdigest())
        or not compare_digest(result.source_sha256, output.source_sha256)
        or not compare_digest(result.output_sha256, output.output_sha256)
        or compare_digest(output.source_sha256, output.output_sha256)
        or not compare_digest(hashlib.sha256(output.content).hexdigest(), output.output_sha256)
    ):
        raise CDRRepeatAVDenied("Нарушена целостность CDR-результата")
    if not output.content.startswith(b"%PDF-") or b"%%EOF" not in output.content[-1024:]:
        raise CDRRepeatAVDenied("CDR-результат не соответствует PDF-контракту")
    return output


def scan_synthetic_cdr_output(
    result: SyntheticCDRResult | SyntheticDOCXResult,
    *,
    scanner: PreflightGatedScanner,
) -> SyntheticCDRAVReceipt:
    """Второй AV для байтов CDR, EICAR до/после обеспечивается гейтом 6.3.3.

    status=clean_reported является только сообщением локального clamd.
    Ошибки приводят к status=error либо исключению; ничего не освобождается
    из карантина и ничего не передаётся в Context Builder.
    """
    if not isinstance(scanner, PreflightGatedScanner):
        raise CDRRepeatAVDenied("Требуется AV-клиент с обязательным EICAR-гейтом")

    output = _validate_synthetic_result(result)
    input_payload = output.content
    expected_source = output.source_sha256
    expected_output = output.output_sha256
    expected_length = output.output_length
    status = "error"
    reason = "scanner_unavailable"
    engine_version = None

    try:
        verdict = scanner.scan(input_payload)
    except Exception:
        # Не показываем stdout/stderr и диагностические детали AV-клиента:
        # любая непредвиденная ошибка также означает запрет допуска.
        verdict = None

    if isinstance(verdict, ClamdVerdict):
        if verdict.status in {"infected_reported", "clean_reported"} and (
            isinstance(verdict.engine_version, str)
            and verdict.engine_version.startswith("ClamAV ")
            and len(verdict.engine_version) <= 200
        ):
            status = verdict.status
            reason = None
            engine_version = verdict.engine_version
        else:
            reason = "invalid_av_verdict"
    elif verdict is not None:
        reason = "invalid_av_verdict"

    # Привязка отчёта к ровно тем байтам, что были поданы на сканирование.
    try:
        current = _validate_synthetic_result(result)
        unchanged = (
            compare_digest(current.source_sha256, expected_source)
            and compare_digest(current.output_sha256, expected_output)
            and current.output_length == expected_length
            and compare_digest(current.content, input_payload)
        )
    except CDRRepeatAVDenied:
        unchanged = False
    if not unchanged:
        status = "error"
        reason = "output_changed"
        engine_version = None

    return SyntheticCDRAVReceipt(
        source_sha256=expected_source,
        output_sha256=expected_output,
        output_length=expected_length,
        status=status,
        reason_code=reason,
        engine_version=engine_version,
        checked_at=datetime.now(UTC),
    )
