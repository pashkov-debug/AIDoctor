"""Ограниченный API ручных выдержек без обработки карантинных файлов."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.access import require_patient
from app.db.session import get_db
from app.models.access import DoctorPatient, User
from app.models.attachment_evidence_draft import (
    AttachmentEvidenceDraft,
    AttachmentEvidenceReadAudit,
)
from app.models.medical_record import MedicalAttachment
from app.models.patient import Patient
from app.schemas.attachment_evidence_draft import EvidenceDraftCreate, EvidenceDraftRead
from app.services.attachment_evidence import InvalidEvidenceDraft, create_manual_draft

router = APIRouter(
    prefix="/patients/{patient_id}/attachments/{attachment_id}/evidence-drafts",
    tags=["attachment-evidence"],
)
SessionDependency = Annotated[Session, Depends(get_db)]
UserDependency = Annotated[User, Depends(current_user)]


def _authorized_attachment(
    patient_id: str,
    attachment_id: str,
    session: SessionDependency,
    user: UserDependency,
) -> MedicalAttachment:
    if user.role != "doctor":
        raise HTTPException(status_code=403, detail="Doctor role required")
    require_patient(session, user, patient_id)
    patient_exists = session.scalar(
        select(Patient.id)
        .where(
            Patient.id == patient_id,
            Patient.deleted_at.is_(None),
        )
        .with_for_update(read=True)
    )
    if patient_exists is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    active_link = session.scalar(
        select(DoctorPatient.id)
        .where(
            DoctorPatient.doctor_id == user.id,
            DoctorPatient.patient_id == patient_id,
        )
        .with_for_update(read=True)
    )
    if active_link is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    attachment = session.scalar(
        select(MedicalAttachment)
        .where(
            MedicalAttachment.id == attachment_id,
            MedicalAttachment.patient_id == patient_id,
        )
        .with_for_update(read=True)
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return attachment


AuthorizedAttachment = Annotated[MedicalAttachment, Depends(_authorized_attachment)]


def _result(item: AttachmentEvidenceDraft) -> EvidenceDraftRead:
    return EvidenceDraftRead(
        id=item.id,
        patient_id=item.patient_id,
        attachment_id=item.attachment_id,
        created_by_id=item.created_by_id,
        created_at=item.created_at,
        source_locator=item.source_locator,
        excerpt=item.excerpt,
        attachment_sha256=item.attachment_sha256,
        excerpt_sha256=item.excerpt_sha256,
    )


@router.post(
    "",
    response_model=EvidenceDraftRead,
    status_code=201,
    summary="Создать непроверенную ручную выдержку для вложения",
)
def add_evidence_draft(
    payload: EvidenceDraftCreate,
    attachment: AuthorizedAttachment,
    session: SessionDependency,
    user: UserDependency,
    response: Response,
) -> EvidenceDraftRead:
    response.headers["Cache-Control"] = "private, no-store"
    try:
        item = create_manual_draft(
            session,
            attachment=attachment,
            actor_id=user.id,
            source_locator=payload.source_locator,
            excerpt=payload.excerpt,
        )
    except InvalidEvidenceDraft as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _result(item)


@router.get(
    "",
    response_model=list[EvidenceDraftRead],
    summary="Последние 50 ручных непроверенных выдержек вложения",
)
def list_evidence_drafts(
    attachment: AuthorizedAttachment,
    session: SessionDependency,
    user: UserDependency,
    response: Response,
) -> list[EvidenceDraftRead]:
    response.headers["Cache-Control"] = "private, no-store"
    items = session.scalars(
        select(AttachmentEvidenceDraft)
        .where(AttachmentEvidenceDraft.attachment_id == attachment.id)
        .order_by(AttachmentEvidenceDraft.created_at.desc(), AttachmentEvidenceDraft.id.desc())
        .limit(50)
    ).all()
    result = [_result(item) for item in items]
    session.add(
        AttachmentEvidenceReadAudit(
            actor_id=user.id,
            patient_id=attachment.patient_id,
            attachment_id=attachment.id,
            returned_count=len(result),
        )
    )
    # Если запись аудита не удалась, ответ с выдержками не возвращается.
    session.commit()
    return result
