"""6.3.3: fail-closed EICAR-гейт для ручного локального AV-сканирования.

Каждому сообщению clean_reported предшествует и следует EICAR-проверка
тем же экземпляром клиента. Совпадение VERSION не аттестует сервер.
Карантин, Context Builder, CDR и парсинг НЕ меняются.
"""

from collections.abc import Callable
from datetime import datetime

from app.services.attachment_clamd import ClamdScanner, ClamdUnavailable, ClamdVerdict
from app.services.attachment_storage import MAX_FILE_BYTES
from app.services.clamd_health import (
    ClamdHealth,
    PreflightFailure,
    validate_signature_date,
    verify_clamd_with_version,
)


class PreflightGatedScanner:
    """Совместим с ClamdScanner.scan(bytes), не хранит байты медицинского файла."""

    def __init__(
        self,
        scanner: ClamdScanner,
        *,
        max_db_age_days: int = 7,
        clock: Callable[[], datetime] | None = None,
    ):
        if not 1 <= max_db_age_days <= 30:
            raise ValueError("Возраст сигнатур должен быть в диапазоне 1–30 дней")
        self._scanner = scanner
        self._max_db_age_days = max_db_age_days
        self._clock = clock

    def _health(self) -> ClamdHealth:
        try:
            return verify_clamd_with_version(
                self._scanner,
                now=self._clock() if self._clock is not None else None,
                max_age_days=self._max_db_age_days,
            )
        except PreflightFailure as exc:
            raise ClamdUnavailable("Контроль EICAR или свежести сигнатур не пройден") from exc

    def scan(self, payload: bytes) -> ClamdVerdict:
        if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_FILE_BYTES:
            raise ValueError("Недопустимый размер медицинских байтов")

        before = self._health()
        verdict = self._scanner.scan(payload)

        # Положительное обнаружение нельзя терять из-за последующих
        # диагностических сбоев: существующий сервис переводит его в rejected.
        if verdict.status == "infected_reported":
            return verdict

        if verdict.status != "clean_reported":
            raise ClamdUnavailable("Неизвестный ответ медицинского сканирования")
        if verdict.engine_version != before.engine_version:
            raise ClamdUnavailable("Версия сканера изменилась во время сканирования")
        try:
            validate_signature_date(
                verdict.engine_version,
                now=self._clock() if self._clock is not None else None,
                max_age_days=self._max_db_age_days,
            )
        except PreflightFailure as exc:
            raise ClamdUnavailable("Версия или свежесть базы не подтверждена") from exc

        after = self._health()
        if after.engine_version != before.engine_version:
            raise ClamdUnavailable("Версия сканера изменилась после сканирования")
        return verdict
