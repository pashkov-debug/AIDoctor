"""6.3.0: аудируемая передача байтов будущему AV-адаптеру без запуска сканера.

В этом модуле НЕ выполняется AV/CDR, нет записи результата AV и нет допуска к
извлечению данных. Только серверный администратор может запросить снимок.
"""

from dataclasses import dataclass, field

from app.db.base import utc_now
from app.models.access import User
from app.models.attachment_security import AttachmentSecurityEvent, AttachmentSecurityReview
from app.models.medical_record import MedicalAttachment
from app.models.patient import Patient
from app.services.attachment_security import (
    STATUS_PRECHECKED,
    STATUS_QUARANTINED,
    STATUS_REJECTED,
    InspectionUnavailable,
    ProcessingProhibited,
    _read_quarantined_file,
)
from app.services.attachment_storage import AttachmentStorage
from sqlalchemy import select
from sqlalchemy.orm import Session


class ScanAccessDenied(PermissionError):
    """Неверная роль или отсутствует доступ к пациенту/вложению."""


@dataclass(frozen=True)
class QuarantineScanInput:
    """Иммутабельные байты для потенциального ИЗОЛИРОВАННОГО AV-процесса.

    Создание объекта не означает, что файл проверен антивирусом или разрешён
    клинический парсинг.
    """

    attachment_id: str
    patient_id: str
    media_type: str
    sha256: str
    content_length: int
    content: bytes = field(repr=False)  # Не протекать в аудит и логи при repr.


def _audit(
    session: Session,
    *,
    attachment: MedicalAttachment,
    actor_id: str,
    outcome: str,
    reason_code: str | None = None,
) -> None:
    session.add(
        AttachmentSecurityEvent(
            actor_id=actor_id,
            patient_id=attachment.patient_id,
            attachment_id=attachment.id,
            action="scan_input",
            outcome=outcome,
            reason_code=reason_code,
        )
    )
    # Fail-closed: байты не выдаются, если запись аудита не закоммичена.
    session.commit()


def capture_quarantined_scan_input(
    session: Session,
    *,
    patient_id: str,
    attachment_id: str,
    actor_id: str,
    storage: AttachmentStorage,
) -> QuarantineScanInput:
    """Проверить права, состояние и байты под блокировкой PostgreSQL.

    Не публиковать через HTTP и не вызывать из парсеров. Будущий адаптер AV
    должен дополнительно изолировать процесс, контролировать ресурсные лимиты
    и сохранять доказуемый вердикт отдельным контрактом.
    """
    role = session.scalar(select(User.role).where(User.id == actor_id))
    if role != "admin":
        raise ScanAccessDenied("Требуется административная роль")

    patient = session.scalar(
        select(Patient.id)
        .where(Patient.id == patient_id, Patient.deleted_at.is_(None))
        .with_for_update(read=True)
    )
    if patient is None:
        raise ScanAccessDenied("Пациент недоступен")

    attachment = session.scalar(
        select(MedicalAttachment)
        .where(
            MedicalAttachment.id == attachment_id,
            MedicalAttachment.patient_id == patient_id,
        )
        .with_for_update()
    )
    if attachment is None:
        raise ScanAccessDenied("Вложение недоступно")

    review = session.scalar(
        select(AttachmentSecurityReview)
        .where(AttachmentSecurityReview.attachment_id == attachment.id)
    )
    if (
        attachment.extraction_status != STATUS_QUARANTINED
        or attachment.extracted_text_ref is not None
        or review is None
        or review.status != STATUS_PRECHECKED
        or review.patient_id != attachment.patient_id
        or review.checked_sha256 != attachment.content_sha256
        or review.checked_length != attachment.content_length
    ):
        status = review.status if review is not None else STATUS_QUARANTINED
        if status not in {STATUS_QUARANTINED, STATUS_PRECHECKED, STATUS_REJECTED}:
            status = STATUS_QUARANTINED
        _audit(
            session,
            attachment=attachment,
            actor_id=actor_id,
            outcome=status,
            reason_code="scan_input_not_ready",
        )
        raise ProcessingProhibited("Файл не готов к передаче AV-адаптеру")

    try:
        inspection = _read_quarantined_file(
            storage, attachment, capture_payload=True
        )
    except InspectionUnavailable:
        _audit(
            session,
            attachment=attachment,
            actor_id=actor_id,
            outcome="error",
            reason_code="storage_unavailable",
        )
        raise

    if not inspection.accepted or inspection.payload is None:
        # Любое расхождение после предпроверки терминально отклоняет файл.
        review.status = STATUS_REJECTED
        review.reason_code = inspection.reason or "scan_input_unavailable"
        review.checked_sha256 = inspection.sha256
        review.checked_length = min(inspection.length, 20 * 1024 * 1024)
        review.checked_by_id = actor_id
        review.checked_at = utc_now()
        _audit(
            session,
            attachment=attachment,
            actor_id=actor_id,
            outcome=STATUS_REJECTED,
            reason_code=review.reason_code,
        )
        raise ProcessingProhibited("Файл изменился или недоступен: карантин сохранён")

    # Передаётся только фиксированная копия проверенных байтов; повторное
    # открытие пути будущим процессом запрещено контрактом.
    result = QuarantineScanInput(
        attachment_id=attachment.id,
        patient_id=attachment.patient_id,
        media_type=attachment.media_type,
        sha256=inspection.sha256,
        content_length=inspection.length,
        content=inspection.payload,
    )
    _audit(
        session,
        attachment=attachment,
        actor_id=actor_id,
        outcome=STATUS_PRECHECKED,
    )
    return result
