"""Ограниченная проверка целостности файла. НЕ антивирус и НЕ допуск к парсингу."""

import hashlib
import io
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from app.db.base import utc_now
from app.models.attachment_security import AttachmentSecurityEvent, AttachmentSecurityReview
from app.models.medical_record import MedicalAttachment
from app.services.attachment_storage import (
    CHUNK_SIZE,
    MAX_FILE_BYTES,
    MEDIA_TYPES,
    AttachmentStorage,
    matches_signature,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

STATUS_QUARANTINED = "quarantined"
STATUS_PRECHECKED = "prechecked_quarantined"
STATUS_REJECTED = "rejected"
AV_STATUS_NOT_SCANNED = "not_scanned"


class InspectionUnavailable(RuntimeError):
    """Проверка не выполнена: состояние карантина не меняется."""


class ProcessingProhibited(PermissionError):
    """Изоляционная граница будущего воркера извлечения."""


@dataclass(frozen=True)
class InspectionResult:
    accepted: bool
    reason: str | None
    sha256: str
    length: int
    payload: bytes | None = field(default=None, repr=False)  # Не выводить медданные в repr.


def _read_quarantined_file(
    storage: AttachmentStorage,
    attachment: MedicalAttachment,
    *,
    capture_payload: bool = False,
) -> InspectionResult:
    """Читаем максимум 20 МиБ, сверяем метаданные и сигнатуру без извлечения контента."""
    extension = Path(attachment.filename).suffix.lower()
    if (
        extension not in MEDIA_TYPES
        or attachment.media_type != MEDIA_TYPES[extension]
        or attachment.content_length < 1
        or attachment.content_length > MAX_FILE_BYTES
        or len(attachment.content_sha256) != 64
        or any(c not in "0123456789abcdef" for c in attachment.content_sha256)
    ):
        return InspectionResult(False, "invalid_metadata", "", 0)

    try:
        path = storage.path_for_download(attachment.storage_key)
    except ValueError:
        return InspectionResult(False, "invalid_storage_key", "", 0)
    if path is None:
        return InspectionResult(False, "storage_missing", "", 0)
    # Не следуем по подменённой подпапке или ссылке за пределы закрытого хранилища.
    if path.parent.is_symlink() or not path.resolve().is_relative_to(storage.root):
        return InspectionResult(False, "unsafe_storage_path", "", 0)

    data = bytearray()
    digest = hashlib.sha256()
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                return InspectionResult(False, "unsafe_storage_path", "", 0)
            while part := stream.read(CHUNK_SIZE):
                data.extend(part)
                digest.update(part)
                if len(data) > MAX_FILE_BYTES:
                    return InspectionResult(False, "size_exceeded", "", len(data))
            after = os.fstat(stream.fileno())
            if (
                before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
                or before.st_ctime_ns != after.st_ctime_ns
            ):
                return InspectionResult(False, "file_changed", "", len(data))
    except FileNotFoundError:
        return InspectionResult(False, "storage_missing", "", 0)
    except OSError as exc:
        raise InspectionUnavailable("Хранилище временно недоступно") from exc

    observed_hash = digest.hexdigest()
    size = len(data)
    if size != attachment.content_length:
        return InspectionResult(False, "size_mismatch", observed_hash, size)
    if observed_hash != attachment.content_sha256:
        return InspectionResult(False, "hash_mismatch", observed_hash, size)
    if not matches_signature(io.BytesIO(data), extension):
        return InspectionResult(False, "signature_mismatch", observed_hash, size)
    return InspectionResult(
        True,
        None,
        observed_hash,
        size,
        bytes(data) if capture_payload else None,
    )


def current_review(
    session: Session, attachment: MedicalAttachment
) -> AttachmentSecurityReview | None:
    return session.scalar(
        select(AttachmentSecurityReview).where(
            AttachmentSecurityReview.attachment_id == attachment.id
        )
    )


def public_status(review: AttachmentSecurityReview | None) -> str:
    return review.status if review is not None else STATUS_QUARANTINED


def record_read(
    session: Session, *, attachment: MedicalAttachment, actor_id: str
) -> AttachmentSecurityReview | None:
    review = current_review(session, attachment)
    session.add(
        AttachmentSecurityEvent(
            actor_id=actor_id,
            patient_id=attachment.patient_id,
            attachment_id=attachment.id,
            action="read",
            outcome=public_status(review),
            reason_code=review.reason_code if review else None,
        )
    )
    # Fail-closed: нельзя вернуть успешный ответ о статусе без коммита аудита.
    session.commit()
    return review


def perform_precheck(
    session: Session,
    *,
    attachment: MedicalAttachment,
    actor_id: str,
    storage: AttachmentStorage,
) -> AttachmentSecurityReview:
    """Вызывается с FOR UPDATE блокировкой строки вложения и проверенными правами."""
    if attachment.extraction_status != STATUS_QUARANTINED or attachment.extracted_text_ref:
        raise ProcessingProhibited("Состояние вложения не допускает предварительную проверку")

    review = current_review(session, attachment)
    if review is not None and review.status == STATUS_REJECTED:
        # Терминальная блокировка. Аудит повторных попыток без чтения файла.
        session.add(
            AttachmentSecurityEvent(
                actor_id=actor_id,
                patient_id=attachment.patient_id,
                attachment_id=attachment.id,
                action="precheck",
                outcome=STATUS_REJECTED,
                reason_code=review.reason_code,
            )
        )
        session.commit()
        return review

    try:
        inspection = _read_quarantined_file(storage, attachment)
    except InspectionUnavailable:
        session.add(
            AttachmentSecurityEvent(
                actor_id=actor_id,
                patient_id=attachment.patient_id,
                attachment_id=attachment.id,
                action="precheck",
                outcome="error",
                reason_code="storage_unavailable",
            )
        )
        session.commit()
        raise

    if review is None:
        review = AttachmentSecurityReview(
            attachment_id=attachment.id,
            patient_id=attachment.patient_id,
            checked_by_id=actor_id,
            status=STATUS_QUARANTINED,  # Заполняется ниже до flush.
            checked_sha256=inspection.sha256,
            checked_length=inspection.length,
        )
        session.add(review)
    review.status = STATUS_PRECHECKED if inspection.accepted else STATUS_REJECTED
    review.reason_code = inspection.reason
    review.checked_sha256 = inspection.sha256
    review.checked_length = min(inspection.length, MAX_FILE_BYTES)
    review.checked_by_id = actor_id
    review.checked_at = utc_now()
    session.add(
        AttachmentSecurityEvent(
            actor_id=actor_id,
            patient_id=attachment.patient_id,
            attachment_id=attachment.id,
            action="precheck",
            outcome=review.status,
            reason_code=review.reason_code,
        )
    )
    session.commit()
    return review


def require_processing_clearance(
    attachment: MedicalAttachment, review: AttachmentSecurityReview | None
) -> None:
    """Стабильная закрытая точка интеграции для будущего ИЗОЛИРОВАННОГО парсера.

    Предпроверка не включает AV/CDR; поэтому в 6.2 НЕТ разрешённого состояния.
    """
    del attachment, review
    raise ProcessingProhibited("Обработка файлов запрещена: AV/CDR не выполнялись")
