"""6.3.1: запуск реального clamd из закрытого карантина с fail-closed аудитом.

НЕТ снятия карантина, HTTP endpoint, автосканирования или допуска парсера.
Выполнять только из доверенного локального административного процесса.
"""

from dataclasses import dataclass

from app.db.base import utc_now
from app.models.access import User
from app.models.attachment_av_scan import AttachmentAVScan
from app.models.attachment_security import AttachmentSecurityEvent, AttachmentSecurityReview
from app.models.medical_record import MedicalAttachment
from app.models.patient import Patient
from app.services.attachment_clamd import ClamdScanner
from app.services.attachment_scan_boundary import (
    QuarantineScanInput,
    capture_quarantined_scan_input,
)
from app.services.attachment_security import (
    STATUS_PRECHECKED,
    STATUS_QUARANTINED,
    STATUS_REJECTED,
    InspectionUnavailable,
    _read_quarantined_file,
)
from app.services.attachment_storage import AttachmentStorage
from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class AVScanReceipt:
    id: str
    status: str
    content_sha256: str
    content_length: int
    reason_code: str | None
    engine_version: str | None


def _persist_report(
    session: Session,
    *,
    snapshot: QuarantineScanInput,
    actor_id: str,
    storage: AttachmentStorage,
    scanner_status: str,
    engine_version: str | None,
    failure: str | None,
) -> AVScanReceipt:
    # Защита от подмены метаданных и смены прав между scan_input и scan_result.
    attachment = session.scalar(
        select(MedicalAttachment)
        .where(
            MedicalAttachment.id == snapshot.attachment_id,
            MedicalAttachment.patient_id == snapshot.patient_id,
        )
        .with_for_update()
    )
    review = session.scalar(
        select(AttachmentSecurityReview)
        .where(AttachmentSecurityReview.attachment_id == snapshot.attachment_id)
        .with_for_update()
    )
    patient_exists = session.scalar(
        select(Patient.id).where(
            Patient.id == snapshot.patient_id, Patient.deleted_at.is_(None)
        )
    )
    role = session.scalar(select(User.role).where(User.id == actor_id))
    status = scanner_status
    reason = failure
    if status not in {"clean_reported", "infected_reported", "error"}:
        status, reason = "error", "invalid_scanner_verdict"
    elif status != "error" and (
        not isinstance(engine_version, str)
        or not engine_version.startswith("ClamAV ")
        or len(engine_version) > 200
    ):
        status, reason = "error", "invalid_scanner_version"

    if (
        attachment is None
        or review is None
        or patient_exists is None
        or role != "admin"
        or attachment.extraction_status != STATUS_QUARANTINED
        or attachment.extracted_text_ref is not None
        or review.status != STATUS_PRECHECKED
        or review.patient_id != snapshot.patient_id
        or review.checked_sha256 != snapshot.sha256
        or review.checked_length != snapshot.content_length
        or attachment.content_sha256 != snapshot.sha256
        or attachment.content_length != snapshot.content_length
    ):
        status = "error"
        reason = "state_changed"
    else:
        try:
            after = _read_quarantined_file(storage, attachment)
        except InspectionUnavailable:
            status = "error"
            reason = "storage_unavailable"
        else:
            if (
                not after.accepted
                or after.sha256 != snapshot.sha256
                or after.length != snapshot.content_length
            ):
                status = "error"
                reason = "postscan_file_changed"
                review.status = STATUS_REJECTED
                review.reason_code = "postscan_file_changed"
                review.checked_by_id = actor_id
                review.checked_at = utc_now()
            elif status == "infected_reported":
                # Сигнал о вредоносности переводит в терминальный карантин.
                review.status = STATUS_REJECTED
                review.reason_code = "av_detected"
                review.checked_by_id = actor_id
                review.checked_at = utc_now()

    if status == "error":
        reason = reason or "scanner_error"
        engine_version = None
    else:
        reason = None
    report = AttachmentAVScan(
        actor_id=actor_id,
        patient_id=snapshot.patient_id,
        attachment_id=snapshot.attachment_id,
        content_sha256=snapshot.sha256,
        content_length=snapshot.content_length,
        status=status,
        reason_code=reason,
        engine_name="clamd",
        engine_version=engine_version,
    )
    session.add(report)
    session.add(
        AttachmentSecurityEvent(
            actor_id=actor_id,
            patient_id=snapshot.patient_id,
            attachment_id=snapshot.attachment_id,
            action="av_scan",
            outcome=(
                STATUS_REJECTED if status == "infected_reported"
                else STATUS_PRECHECKED if status == "clean_reported" else "error"
            ),
            reason_code="av_detected" if status == "infected_reported" else reason,
        )
    )
    # Зафиксировать generated ID до commit: возврат не зависит от SQLAlchemy Session.
    session.flush()
    receipt = AVScanReceipt(
        id=report.id,
        status=report.status,
        content_sha256=report.content_sha256,
        content_length=report.content_length,
        reason_code=report.reason_code,
        engine_version=report.engine_version,
    )
    # Результат сканирования не считается успешным без атомарной записи аудита.
    session.commit()
    return receipt


def scan_quarantined_attachment(
    session: Session,
    *,
    patient_id: str,
    attachment_id: str,
    actor_id: str,
    storage: AttachmentStorage,
    scanner: ClamdScanner,
) -> AVScanReceipt:
    """Сканирование вручную; возвращает сохранённый технический verdict.

    Даже clean_reported НЕ открывает парсер и не меняет extraction_status.
    Источник байтов — только audit-confirmed capture_quarantined_scan_input.
    """
    snapshot = capture_quarantined_scan_input(
        session,
        patient_id=patient_id,
        attachment_id=attachment_id,
        actor_id=actor_id,
        storage=storage,
    )
    status = "error"
    version = None
    reason = "scanner_unavailable"
    try:
        verdict = scanner.scan(snapshot.content)
        status = verdict.status
        version = verdict.engine_version
        reason = None
    except Exception:
        # Ошибка или некорректный объект стороннего AV-адаптера не должны
        # обходить фиксацию error + audit. Никаких подробностей/PHI в БД.
        # Ошибки записи отчёта/аудита ниже НЕ перехватываем: fail-closed.
        pass
    return _persist_report(
        session,
        snapshot=snapshot,
        actor_id=actor_id,
        storage=storage,
        scanner_status=status,
        engine_version=version,
        failure=reason,
    )
