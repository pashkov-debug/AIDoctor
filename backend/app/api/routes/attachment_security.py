"""Статус и повторная предварительная проверка вложений (без AV/парсера)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.access import require_patient
from app.core.config import settings
from app.db.session import get_db
from app.models.access import DoctorPatient, User
from app.models.medical_record import MedicalAttachment
from app.models.patient import Patient
from app.schemas.attachment_security import AttachmentSecurityRead
from app.services.attachment_security import (
    AV_STATUS_NOT_SCANNED,
    InspectionUnavailable,
    ProcessingProhibited,
    perform_precheck,
    public_status,
    record_read,
)
from app.services.attachment_storage import AttachmentStorage

router = APIRouter(
    prefix="/patients/{patient_id}/attachments/{attachment_id}/security",
    tags=["attachment-security"],
)
SessionDependency = Annotated[Session, Depends(get_db)]
UserDependency = Annotated[User, Depends(current_user)]


def _require_attachment(
    session: Session,
    user: User,
    patient_id: str,
    attachment_id: str,
    *,
    write: bool,
) -> MedicalAttachment:
    if write and user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    if user.role not in {"doctor", "admin"}:
        raise HTTPException(status_code=403, detail="Doctor or admin role required")
    require_patient(session, user, patient_id)
    patient = session.scalar(
        select(Patient.id)
        .where(Patient.id == patient_id, Patient.deleted_at.is_(None))
        .with_for_update(read=True)
    )
    if patient is None:
        raise HTTPException(status_code=404, detail="Patient not found")
    if user.role == "doctor":
        link = session.scalar(
            select(DoctorPatient.id)
            .where(
                DoctorPatient.doctor_id == user.id,
                DoctorPatient.patient_id == patient_id,
            )
            .with_for_update(read=True)
        )
        if link is None:
            raise HTTPException(status_code=404, detail="Patient not found")
    attachment = session.scalar(
        select(MedicalAttachment)
        .where(
            MedicalAttachment.id == attachment_id,
            MedicalAttachment.patient_id == patient_id,
        )
        .with_for_update(read=not write)
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return attachment


def _response(item: MedicalAttachment, review) -> AttachmentSecurityRead:
    return AttachmentSecurityRead(
        patient_id=item.patient_id,
        attachment_id=item.id,
        status=public_status(review),
        antivirus_status=AV_STATUS_NOT_SCANNED,
        checked_at=review.checked_at if review is not None else None,
        reason_code=review.reason_code if review is not None else None,
    )


@router.get("", response_model=AttachmentSecurityRead)
def security_status(
    patient_id: str,
    attachment_id: str,
    session: SessionDependency,
    user: UserDependency,
    response: Response,
) -> AttachmentSecurityRead:
    attachment = _require_attachment(session, user, patient_id, attachment_id, write=False)
    review = record_read(session, attachment=attachment, actor_id=user.id)
    response.headers["Cache-Control"] = "private, no-store"
    return _response(attachment, review)


@router.post("/precheck", response_model=AttachmentSecurityRead)
def precheck_attachment(
    patient_id: str,
    attachment_id: str,
    session: SessionDependency,
    user: UserDependency,
    response: Response,
) -> AttachmentSecurityRead:
    attachment = _require_attachment(session, user, patient_id, attachment_id, write=True)
    storage = AttachmentStorage(settings.attachments_dir)
    try:
        review = perform_precheck(session, attachment=attachment, actor_id=user.id, storage=storage)
    except InspectionUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ProcessingProhibited as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response.headers["Cache-Control"] = "private, no-store"
    return _response(attachment, review)
