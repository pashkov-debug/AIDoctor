"""Данные врача отдельно от пациентского контекста и от LLM-провайдера."""

from datetime import UTC, datetime

from app.models.access import User
from app.models.doctor_settings import DoctorSettings, DoctorSettingsAudit
from app.schemas.doctor_settings import (
    ClinicalFields,
    DoctorContextRead,
    DoctorSettingsRead,
    ProfileFields,
    RussianGuidelinesContext,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

PROFILE_NAMES = ("full_name", "specialty", "institution", "professional_info", "contact_email")
CLINICAL_NAMES = ("practice_country", "rki_mode", "institution_type", "clinical_specialty")
DEFAULT_CLINICAL = ClinicalFields()


def read_settings(db: Session, doctor_id: str) -> DoctorSettingsRead:
    record = db.get(DoctorSettings, doctor_id)
    if record is None:
        return DoctorSettingsRead(
            version=0,
            profile=ProfileFields(),
            clinical=DEFAULT_CLINICAL,
        )
    return DoctorSettingsRead(
        version=record.version,
        profile=ProfileFields.model_validate(
            {name: getattr(record, name) for name in PROFILE_NAMES}
        ),
        clinical=ClinicalFields.model_validate(
            {name: getattr(record, name) for name in CLINICAL_NAMES}
        ),
    )


def read_doctor_context(db: Session, doctor_id: str) -> DoctorContextRead:
    settings = read_settings(db, doctor_id)
    return DoctorContextRead(
        doctor_id=doctor_id,
        profile_version=settings.version,
        country=settings.clinical.practice_country,
        rki=RussianGuidelinesContext(mode=settings.clinical.rki_mode),
        institution_type=settings.clinical.institution_type,
        specialty=settings.clinical.clinical_specialty,
    )


def update_settings(
    db: Session,
    doctor: User,
    *,
    section: str,
    expected_version: int,
    values: dict,
) -> DoctorSettingsRead:
    if section not in {"profile", "clinical"}:
        raise ValueError("Unknown settings section")
    allowed = PROFILE_NAMES if section == "profile" else CLINICAL_NAMES
    if set(values) != set(allowed):
        raise ValueError("Incomplete settings section")
    record = db.scalar(
        select(DoctorSettings).where(DoctorSettings.doctor_id == doctor.id).with_for_update()
    )
    current_version = record.version if record is not None else 0
    if current_version != expected_version:
        raise HTTPException(status_code=409, detail="Settings version conflict; reload")
    previous = (
        {name: getattr(record, name) for name in allowed}
        if record is not None
        else {name: ("disabled" if name == "rki_mode" else None) for name in allowed}
    )
    changed = [name for name in allowed if previous[name] != values[name]]
    if not changed:
        return read_settings(db, doctor.id)
    if record is None:
        record = DoctorSettings(doctor_id=doctor.id, version=1)
        db.add(record)
    else:
        record.version += 1
    for name in allowed:
        setattr(record, name, values[name])
    record.updated_at = datetime.now(UTC)
    db.add(
        DoctorSettingsAudit(
            doctor_id=doctor.id,
            actor_id=doctor.id,
            section=section,
            from_version=current_version,
            to_version=record.version,
            changed_fields=changed,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Первая параллельная запись может конкурировать за doctor_id (PK).
        raise HTTPException(status_code=409, detail="Settings version conflict; reload") from exc
    return read_settings(db, doctor.id)
