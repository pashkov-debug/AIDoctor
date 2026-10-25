"""Аутентификация врача по выделенному ключу Site, ограничения пациента."""

import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.models.access import DoctorPatient, User
from app.models.ai_workspace import AIRequest
from app.models.patient import Patient
from app.models.site_doctor_credential import SiteDoctorCredential
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

TOKEN_PREFIX = "aidoc_site_"
TOKEN_DAYS = 90


def site_enabled() -> bool:
    return settings.app_env == "test" and os.getenv("AIDOCTOR_SITE_MULTI_DOCTOR_ENABLED") == "1"


def hash_site_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def new_site_key() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(48)


def authenticate_site_doctor(db: Session, key: str | None) -> User:
    if not site_enabled():
        raise HTTPException(404, "Интеграция Site выключена")
    if (
        not isinstance(key, str)
        or not key.startswith(TOKEN_PREFIX)
        or len(key) > 200
        or len(key) < 60
    ):
        raise HTTPException(401, "Неверный ключ интеграции")
    digest = hash_site_key(key)
    row = db.scalar(
        select(SiteDoctorCredential).where(
            SiteDoctorCredential.key_hash == digest,
            SiteDoctorCredential.enabled.is_(True),
            SiteDoctorCredential.revoked_at.is_(None),
        )
    )
    if row is None or row.expires_at <= datetime.now(UTC):
        raise HTTPException(401, "Ключ интеграции отозван или истёк")
    # Запрещаем доверять doctor_id, пришедшему из аргументов MCP.
    doctor = db.get(User, row.doctor_id)
    if doctor is None or doctor.role != "doctor":
        raise HTTPException(403, "Учётная запись врача недоступна")
    return doctor


def require_site_request(
    db: Session,
    doctor: User,
    patient_id: str,
    request_id: str,
    *,
    lock: bool = False,
) -> AIRequest:
    query = select(AIRequest).where(
        AIRequest.id == request_id,
        AIRequest.patient_id == patient_id,
        AIRequest.doctor_id == doctor.id,
    )
    if lock:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise HTTPException(404, "AI-запрос недоступен")

    patient = db.get(Patient, patient_id)
    if patient is None or patient.deleted_at is not None:
        raise HTTPException(404, "Пациент недоступен")
    link = db.scalar(
        select(DoctorPatient.id).where(
            DoctorPatient.doctor_id == doctor.id,
            DoctorPatient.patient_id == patient_id,
        )
    )
    if link is None:
        raise HTTPException(404, "Пациент недоступен")

    # Для несинтетических данных согласие остаётся обязательным.
    # Демо-флаг окружения не подменяет согласие и не даёт дополнительных прав.
    metadata = patient.demographics_json
    synthetic = isinstance(metadata, dict) and metadata.get("synthetic") is True
    other_allowed = isinstance(metadata, dict) and metadata.get("external_ai_consent") is True
    if not synthetic and not other_allowed:
        raise HTTPException(
            403,
            "Для несинтетического случая требуется отдельное разрешение",
        )
    return row


def expiry_from_now(days: int = TOKEN_DAYS) -> datetime:
    if days < 1 or days > 90:
        raise ValueError("Максимальный срок действия 90 суток")
    return datetime.now(UTC) + timedelta(days=days)
