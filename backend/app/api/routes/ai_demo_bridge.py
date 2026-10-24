"""Только синтетический обратный канал Site Builder -> AI-черновик.

Публичный endpoint не читает медицинские данные, не создаёт назначения
и работает только при явном включении на тестовом сервере.
"""

import hashlib
import hmac
import json
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.api.routes.ai_workspace import _authorize
from app.core.config import settings
from app.db.session import get_db
from app.models.access import DoctorPatient, User
from app.models.ai_demo_bridge import AIDemoAnalysis
from app.models.ai_workspace import AIRequest
from app.models.patient import Patient
from app.schemas.ai_demo_bridge import DemoAnalysisRead, DemoAnalysisSubmit
from app.services.ai_agent_context import get_agent_context
from app.services.ai_review import _fresh

router = APIRouter(tags=["site-builder-demo-bridge"])
DB = Annotated[Session, Depends(get_db)]
Actor = Annotated[User, Depends(current_user)]
BridgeToken = Annotated[str | None, Header(alias="X-AIDoctor-Bridge-Token")]
MAX_BODY_BYTES = 64 * 1024


def _bridge_auth(token: str | None) -> None:
    """Секрет известен только обработчику Site и контейнеру AIDoctor."""
    secret = os.environ.get("AIDOCTOR_SITE_BRIDGE_TOKEN", "")
    enabled = (
        settings.app_env == "test"
        and os.environ.get("AIDOCTOR_DEMO_CALLBACK_ENABLED") == "1"
        and len(secret) >= 40
    )
    if not enabled:
        raise HTTPException(404, "Демонстрационный обратный канал выключен")
    if token is None or not hmac.compare_digest(token, secret):
        raise HTTPException(401, "Недействительный токен обратного канала")


def _canonical(payload: DemoAnalysisSubmit) -> tuple[dict, str]:
    data = payload.model_dump(mode="json")
    raw = json.dumps(
        data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return data, hashlib.sha256(raw).hexdigest()


def _read(row: AIDemoAnalysis) -> DemoAnalysisRead:
    return DemoAnalysisRead(
        request_id=row.request_id,
        patient_id=row.patient_id,
        submitted_at=row.created_at.isoformat(),
        payload_sha256=row.payload_sha256,
        analysis=DemoAnalysisSubmit.model_validate(row.payload_json),
    )


@router.post(
    "/integrations/site-builder/demo-analyses",
    response_model=DemoAnalysisRead,
    status_code=201,
    summary="Приём только синтетического анализа (без назначения лечения)",
)
async def submit_demo_analysis(
    payload: DemoAnalysisSubmit,
    request: Request,
    response: Response,
    db: DB,
    bridge_token: BridgeToken = None,
) -> DemoAnalysisRead:
    _bridge_auth(bridge_token)
    if len(await request.body()) > MAX_BODY_BYTES:
        raise HTTPException(413, "Превышен лимит размера ответа")
    response.headers["Cache-Control"] = "private, no-store"

    patient_id = str(payload.patient_id)
    request_id = str(payload.request_id)
    row = db.scalar(
        select(AIRequest)
        .where(
            AIRequest.id == request_id,
            AIRequest.patient_id == patient_id,
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "Подготовленный AI-запрос не найден")
    doctor = db.get(User, row.doctor_id)
    patient = db.get(Patient, patient_id)
    # Только заранее заведённый синтетический демонстрационный врач.
    if (
        doctor is None
        or doctor.role != "doctor"
        or doctor.username != "doctor_ui1"
        or patient is None
        or patient.deleted_at is not None
        or not isinstance(patient.demographics_json, dict)
        or patient.demographics_json.get("synthetic") is not True
    ):
        raise HTTPException(403, "Разрешены только демонстрационные запросы")

    link = db.scalar(
        select(DoctorPatient.id).where(
            DoctorPatient.doctor_id == row.doctor_id,
            DoctorPatient.patient_id == patient_id,
        )
    )
    if link is None:
        raise HTTPException(403, "Связь врача с пациентом больше не действует")

    if (
        not hmac.compare_digest(row.context_sha256, payload.context_sha256)
        or row.review_orders_sha256 is None
        or not hmac.compare_digest(row.review_orders_sha256, payload.orders_sha256)
    ):
        raise HTTPException(409, "Хеш сохранённого запроса не совпадает")
    # Проверяются зафиксированный snapshot и актуальность клинических данных.
    get_agent_context(db, row.doctor_id, patient_id, request_id)
    _fresh(db, row)

    data, digest = _canonical(payload)
    existing = db.scalar(select(AIDemoAnalysis).where(AIDemoAnalysis.request_id == request_id))
    if existing is not None:
        if not hmac.compare_digest(existing.payload_sha256, digest):
            raise HTTPException(409, "Для этого запроса уже принят другой анализ")
        return _read(existing)

    result = AIDemoAnalysis(
        request_id=request_id,
        patient_id=patient_id,
        doctor_id=row.doctor_id,
        context_sha256=payload.context_sha256,
        orders_sha256=payload.orders_sha256,
        payload_sha256=digest,
        payload_json=data,
    )
    db.add(result)
    try:
        db.commit()
        db.refresh(result)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Анализ уже сохранён параллельным запросом") from exc
    except Exception:
        db.rollback()
        raise
    return _read(result)


@router.get(
    "/patients/{patient_id}/ai-requests/{request_id}/demo-analysis",
    response_model=DemoAnalysisRead,
    summary="Черновик внешнего AI-анализа только для лечащего врача",
)
def get_demo_analysis(
    patient_id: str,
    request_id: str,
    db: DB,
    actor: Actor,
    response: Response,
) -> DemoAnalysisRead:
    _authorize(db, actor, patient_id)
    response.headers["Cache-Control"] = "private, no-store"
    row = db.scalar(
        select(AIDemoAnalysis).where(
            AIDemoAnalysis.request_id == request_id,
            AIDemoAnalysis.patient_id == patient_id,
            AIDemoAnalysis.doctor_id == actor.id,
        )
    )
    if row is None:
        raise HTTPException(404, "AI-анализ ещё не поступил")
    return _read(row)
