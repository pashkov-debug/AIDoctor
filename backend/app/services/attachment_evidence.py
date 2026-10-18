"""Ручные выдержки: происхождение, дедупликация, отсутствие продвижения в контекст."""

import hashlib
import unicodedata

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.attachment_evidence_draft import AttachmentEvidenceDraft
from app.models.medical_record import MedicalAttachment

MAX_LOCATOR = 120
MAX_EXCERPT = 2000


class InvalidEvidenceDraft(ValueError):
    pass


def normalize_evidence(source_locator: str, excerpt: str) -> tuple[str, str, str]:
    """NFC, обрезка внешних пробелов; внутри текста значимое форматирование сохраняется."""
    locator = unicodedata.normalize("NFC", source_locator).strip()
    text = unicodedata.normalize("NFC", excerpt).strip()
    if (
        not locator
        or len(locator) > MAX_LOCATOR
        or any(ord(c) < 32 or ord(c) == 127 for c in locator)
    ):
        raise InvalidEvidenceDraft("Недопустимый локатор источника")
    if not text or len(text) > MAX_EXCERPT or "\x00" in text:
        raise InvalidEvidenceDraft("Недопустимый текст выдержки")
    if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
        raise InvalidEvidenceDraft("Недопустимые управляющие символы")
    return locator, text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def create_manual_draft(
    session: Session,
    *,
    attachment: MedicalAttachment,
    actor_id: str,
    source_locator: str,
    excerpt: str,
) -> AttachmentEvidenceDraft:
    """Вызывается после проверки прав; не читает содержимое файла и не меняет контекст."""
    locator, text, digest = normalize_evidence(source_locator, excerpt)
    values = {
        "patient_id": attachment.patient_id,
        "attachment_id": attachment.id,
        "created_by_id": actor_id,
        "attachment_sha256": attachment.content_sha256,
        "source_locator": locator,
        "excerpt": text,
        "excerpt_sha256": digest,
    }
    # ON CONFLICT предотвращает дубль даже при параллельных запросах.
    command = (
        pg_insert(AttachmentEvidenceDraft)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_attachment_evidence_draft_identity")
        .returning(AttachmentEvidenceDraft.id)
    )
    inserted_id = session.scalar(command)
    if inserted_id is None:
        # PostgreSQL READ COMMITTED: следующий SELECT видит победившую транзакцию.
        existing = session.scalar(
            select(AttachmentEvidenceDraft).where(
                AttachmentEvidenceDraft.attachment_id == attachment.id,
                AttachmentEvidenceDraft.created_by_id == actor_id,
                AttachmentEvidenceDraft.source_locator == locator,
                AttachmentEvidenceDraft.excerpt_sha256 == digest,
            )
        )
        if existing is None:
            raise RuntimeError("Не удалось прочитать дубликат выдержки")
        result = existing
    else:
        result = session.get(AttachmentEvidenceDraft, inserted_id)
        if result is None:
            raise RuntimeError("Не удалось прочитать созданную выдержку")
    session.commit()
    return result
