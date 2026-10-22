"""6.4.0: аудитируемый снимок кандидата для будущей изолированной CDR.

НИКОГДА не выдаёт разрешение парсеру, не запускает CDR, OCR или LLM.
Даже последний clean_reported — технический отчёт, НЕ аттестация AV.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from app.db.base import utc_now
from app.models.access import User
from app.models.attachment_av_scan import AttachmentAVScan
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

# Поддержка означает только тип входного снимка, не наличие CDR-движка.
CDR_INPUT_FORMATS = {
    ".pdf": "application/pdf",
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
}
MAX_AV_REPORT_AGE = timedelta(hours=24)


class CDRAccessDenied(PermissionError):
    """Администратор не имеет права на указанный объект."""


@dataclass(frozen=True)
class QuarantinedCDRCandidate:
    """Снимок для будущей изолированной среды. НЕ безопасный документ.

    content никогда не сохраняется в БД/аудите и не выводится в repr.
    """

    patient_id: str
    attachment_id: str
    av_report_id: str
    media_type: str
    source_sha256: str
    content_length: int
    content: bytes = field(repr=False)

    @property
    def processing_allowed(self) -> bool:
        """Никакой экземпляр кандидата не может разрешать обработку."""
        return False


def cdr_candidate_rejection_reason(
    attachment: MedicalAttachment,
    review: AttachmentSecurityReview | None,
    latest_av: AttachmentAVScan | None,
    *,
    now: datetime,
) -> str | None:
    """Политика предварительного отбора, не выдающая клинического допуска."""
    if attachment.extraction_status != STATUS_QUARANTINED or (
        attachment.extracted_text_ref is not None
    ):
        return "invalid_extraction_state"
    extension = Path(attachment.filename).suffix.lower()
    if CDR_INPUT_FORMATS.get(extension) != attachment.media_type:
        return "unsupported_format"
    if (
        review is None
        or review.status != STATUS_PRECHECKED
        or review.patient_id != attachment.patient_id
        or review.attachment_id != attachment.id
        or review.checked_sha256 != attachment.content_sha256
        or review.checked_length != attachment.content_length
    ):
        return "precheck_not_ready"
    if latest_av is None:
        return "av_report_missing"
    if latest_av.status != "clean_reported":
        return "av_not_clean"
    if (
        latest_av.attachment_id != attachment.id
        or latest_av.patient_id != attachment.patient_id
        or latest_av.content_sha256 != attachment.content_sha256
        or latest_av.content_length != attachment.content_length
        or latest_av.engine_name != "clamd"
        or latest_av.reason_code is not None
        or not isinstance(latest_av.engine_version, str)
        or not latest_av.engine_version.startswith("ClamAV ")
    ):
        return "av_report_mismatch"
    # PG TIMESTAMPTZ должен возвращать aware datetime. Не доверяем naive
    # или времени из будущего; изменение часов приводит к fail-closed.
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or latest_av.created_at is None
        or latest_av.created_at.tzinfo is None
        or review.checked_at is None
        or review.checked_at.tzinfo is None
    ):
        return "invalid_av_time"
    if (
        latest_av.created_at > now
        or latest_av.created_at < now - MAX_AV_REPORT_AGE
        or latest_av.created_at < review.checked_at
    ):
        return "av_report_stale"
    return None


def _audit_cdr_input(
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
            action="cdr_input",
            outcome=outcome,
            reason_code=reason_code,
        )
    )
    # Fail-closed: успешный снимок нельзя вернуть до COMMIT аудита.
    session.commit()


def prepare_quarantined_cdr_candidate(
    session: Session,
    *,
    patient_id: str,
    attachment_id: str,
    actor_id: str,
    storage: AttachmentStorage,
) -> QuarantinedCDRCandidate:
    """Только локальный административный процесс, не HTTP и не парсер.

    Нет запуска CDR. Возвращаемые байты считаются опасными даже после
    технического отчёта AV. Вызов не меняет extraction_status и не снимает
    карантин, работает под блокировкой строки файла.
    """
    role = session.scalar(select(User.role).where(User.id == actor_id))
    if role != "admin":
        raise CDRAccessDenied("Недостаточно прав")

    patient_exists = session.scalar(
        select(Patient.id)
        .where(Patient.id == patient_id, Patient.deleted_at.is_(None))
        .with_for_update(read=True)
    )
    if patient_exists is None:
        raise CDRAccessDenied("Пациент недоступен")

    attachment = session.scalar(
        select(MedicalAttachment)
        .where(
            MedicalAttachment.id == attachment_id,
            MedicalAttachment.patient_id == patient_id,
        )
        .with_for_update()
    )
    if attachment is None:
        raise CDRAccessDenied("Вложение недоступно")

    review = session.scalar(
        select(AttachmentSecurityReview)
        .where(AttachmentSecurityReview.attachment_id == attachment.id)
        .with_for_update()
    )
    # Проверяем ПОСЛЕДНИЙ отчёт, а не произвольный старый положительный.
    latest_av = session.scalar(
        select(AttachmentAVScan)
        .where(AttachmentAVScan.attachment_id == attachment.id)
        .order_by(AttachmentAVScan.created_at.desc(), AttachmentAVScan.id.desc())
        .limit(1)
    )
    reason = cdr_candidate_rejection_reason(attachment, review, latest_av, now=utc_now())
    if reason is not None:
        _audit_cdr_input(
            session,
            attachment=attachment,
            actor_id=actor_id,
            outcome="error",
            reason_code=reason,
        )
        raise ProcessingProhibited("CDR-кандидат не подготовлен, карантин сохранён")

    try:
        inspection = _read_quarantined_file(storage, attachment, capture_payload=True)
    except InspectionUnavailable:
        _audit_cdr_input(
            session,
            attachment=attachment,
            actor_id=actor_id,
            outcome="error",
            reason_code="storage_unavailable",
        )
        raise

    if (
        not inspection.accepted
        or inspection.payload is None
        or inspection.sha256 != latest_av.content_sha256
        or inspection.length != latest_av.content_length
    ):
        # Подмена файла — терминальный отказ, только вместе с аудитом.
        review.status = STATUS_REJECTED
        review.reason_code = inspection.reason or "cdr_input_mismatch"
        review.checked_sha256 = inspection.sha256
        review.checked_length = min(inspection.length, 20 * 1024 * 1024)
        review.checked_by_id = actor_id
        review.checked_at = utc_now()
        _audit_cdr_input(
            session,
            attachment=attachment,
            actor_id=actor_id,
            outcome=STATUS_REJECTED,
            reason_code=review.reason_code,
        )
        raise ProcessingProhibited("Байты вложения изменились, карантин сохранён")

    # Фиксированные байты исходника, не путь. Никакой дальнейшей передачи
    # или выполнения в этом инкременте.
    result = QuarantinedCDRCandidate(
        patient_id=attachment.patient_id,
        attachment_id=attachment.id,
        av_report_id=latest_av.id,
        media_type=attachment.media_type,
        source_sha256=inspection.sha256,
        content_length=inspection.length,
        content=inspection.payload,
    )
    _audit_cdr_input(
        session,
        attachment=attachment,
        actor_id=actor_id,
        outcome=STATUS_PRECHECKED,
    )
    return result
