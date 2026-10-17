"""API медицинских вложений: права доступа проверяются до чтения оригинала."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.access import require_patient
from app.core.config import settings
from app.db.session import get_db
from app.models.access import User
from app.models.medical_record import MedicalAttachment
from app.models.patient import Patient
from app.services.attachment_storage import AttachmentRejected, AttachmentStorage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/patients/{patient_id}/attachments", tags=["attachments"])

SessionDependency = Annotated[Session, Depends(get_db)]
UserDependency = Annotated[User, Depends(current_user)]


class AttachmentRead(BaseModel):
    id: str
    patient_id: str
    filename: str
    media_type: str
    content_length: int
    content_sha256: str
    extraction_status: str


def _storage() -> AttachmentStorage:
    return AttachmentStorage(settings.attachments_dir)


def _check_patient(session: Session, user: User, patient_id: str) -> None:
    require_patient(session, user, patient_id)
    patient = session.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Patient not found")


def _response(item: MedicalAttachment) -> AttachmentRead:
    return AttachmentRead(
        id=item.id,
        patient_id=item.patient_id,
        filename=item.filename,
        media_type=item.media_type,
        content_length=item.content_length,
        content_sha256=item.content_sha256,
        extraction_status=item.extraction_status,
    )


@router.post(
    "",
    response_model=AttachmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Загрузить медицинское вложение",
)
def upload_attachment(
    patient_id: str,
    file: Annotated[UploadFile, File(description="PDF, DOC/DOCX, изображения, аудио")],
    session: SessionDependency,
    user: UserDependency,
) -> AttachmentRead:
    _check_patient(session, user, patient_id)
    storage = _storage()
    stored = None
    try:
        stored = storage.save(file.file, file.filename)
        item = MedicalAttachment(
            patient_id=patient_id,
            uploaded_by_id=user.id,
            filename=stored.filename,
            media_type=stored.media_type,
            content_sha256=stored.content_sha256,
            content_length=stored.content_length,
            storage_key=stored.key,
            extraction_status="quarantined",
        )
        session.add(item)
        session.flush()
        result = _response(item)
        session.commit()
        return result
    except AttachmentRejected as exc:
        session.rollback()
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except Exception:
        session.rollback()
        if stored is not None:
            try:
                storage.delete(stored.key)
            except OSError:
                logger.exception("Не удалось очистить файл после сбоя транзакции")
        raise
    finally:
        file.file.close()


@router.get("", response_model=list[AttachmentRead], summary="Список вложений пациента")
def list_attachments(
    patient_id: str,
    session: SessionDependency,
    user: UserDependency,
) -> list[AttachmentRead]:
    _check_patient(session, user, patient_id)
    items = session.scalars(
        select(MedicalAttachment)
        .where(MedicalAttachment.patient_id == patient_id)
        .order_by(MedicalAttachment.created_at.desc(), MedicalAttachment.id)
        .limit(100)
    ).all()
    return [_response(item) for item in items]


@router.get("/{attachment_id}", summary="Скачать медицинское вложение")
def download_attachment(
    patient_id: str,
    attachment_id: str,
    session: SessionDependency,
    user: UserDependency,
) -> FileResponse:
    _check_patient(session, user, patient_id)
    item = session.get(MedicalAttachment, attachment_id)
    if item is None or item.patient_id != patient_id:
        raise HTTPException(status_code=404, detail="Attachment not found")
    storage = _storage()
    try:
        path = storage.path_for_download(item.storage_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Attachment not found") from exc
    if path is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return FileResponse(
        path,
        filename=item.filename,
        media_type=item.media_type,
        content_disposition_type="attachment",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
