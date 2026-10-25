"""Изолированное чтение и приём AI-черновиков от Site для разных врачей.

Источник прав: персональный серверный ключ врача + действующая связь с
пациентом + принадлежность AI-запроса этому врачу.
"""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.routes.ai_demo_bridge import MAX_BODY_BYTES, _canonical, _read
from app.db.session import get_db
from app.models.ai_demo_bridge import AIDemoAnalysis
from app.models.site_doctor_credential import SiteDoctorAccessAudit
from app.schemas.ai_agent_context import AIAgentContextRead
from app.schemas.ai_demo_bridge import DemoAnalysisRead, DemoAnalysisSubmit
from app.schemas.ai_review import DraftRead
from app.schemas.ai_structured_proposals import StructuredProposalSubmit
from app.services.ai_agent_context import get_agent_context
from app.services.ai_review import _fresh, import_structured_proposals
from app.services.site_doctor_access import (
    authenticate_site_doctor,
    require_site_request,
)

router = APIRouter(tags=["site-builder-v2"])
DB = Annotated[Session, Depends(get_db)]
DoctorKey = Annotated[str | None, Header(alias="X-AIDoctor-Doctor-Key")]


@router.get(
    "/integrations/site-builder/v2/agent-context",
    response_model=AIAgentContextRead,
)
def read_site_context(
    patient_id: str,
    request_id: str,
    db: DB,
    response: Response,
    doctor_key: DoctorKey = None,
) -> AIAgentContextRead:
    response.headers["Cache-Control"] = "no-store"
    doctor = authenticate_site_doctor(db, doctor_key)
    row = require_site_request(db, doctor, patient_id, request_id)
    context = get_agent_context(db, doctor.id, patient_id, request_id)
    _fresh(db, row)
    db.add(
        SiteDoctorAccessAudit(
            doctor_id=doctor.id,
            patient_id=patient_id,
            request_id=request_id,
            action="read_context",
        )
    )
    db.commit()
    return context


@router.post(
    "/integrations/site-builder/v2/analyses",
    response_model=DemoAnalysisRead,
    status_code=201,
)
async def submit_site_analysis(
    payload: DemoAnalysisSubmit,
    request: Request,
    response: Response,
    db: DB,
    doctor_key: DoctorKey = None,
) -> DemoAnalysisRead:
    response.headers["Cache-Control"] = "no-store"
    if len(await request.body()) > MAX_BODY_BYTES:
        raise HTTPException(413, "Превышен размер ответа")
    doctor = authenticate_site_doctor(db, doctor_key)
    patient_id = str(payload.patient_id)
    request_id = str(payload.request_id)
    row = require_site_request(db, doctor, patient_id, request_id, lock=True)
    if (
        not hmac.compare_digest(row.context_sha256, payload.context_sha256)
        or row.review_orders_sha256 is None
        or not hmac.compare_digest(row.review_orders_sha256, payload.orders_sha256)
    ):
        raise HTTPException(409, "Контекст исходного AI-запроса изменился")
    get_agent_context(db, doctor.id, patient_id, request_id)
    _fresh(db, row)

    data, digest = _canonical(payload)
    existing = db.scalar(select(AIDemoAnalysis).where(AIDemoAnalysis.request_id == request_id))
    if existing is not None:
        if not hmac.compare_digest(existing.payload_sha256, digest):
            raise HTTPException(409, "У запроса уже есть другой AI-черновик")
        # Идемпотентный ответ: не создаём вторую запись или события.
        return _read(existing)

    analysis = AIDemoAnalysis(
        request_id=request_id,
        patient_id=patient_id,
        doctor_id=doctor.id,
        context_sha256=payload.context_sha256,
        orders_sha256=payload.orders_sha256,
        payload_sha256=digest,
        payload_json=data,
    )
    db.add(analysis)
    db.add(
        SiteDoctorAccessAudit(
            doctor_id=doctor.id,
            patient_id=patient_id,
            request_id=request_id,
            action="submit_draft",
        )
    )
    try:
        db.commit()
        db.refresh(analysis)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "AI-анализ уже сохранён") from exc
    except Exception:
        db.rollback()
        raise
    return _read(analysis)


@router.post(
    "/integrations/site-builder/v2/structured-proposals",
    response_model=DraftRead,
    status_code=201,
)
async def submit_site_structured_proposals(
    payload: StructuredProposalSubmit,
    request: Request,
    response: Response,
    db: DB,
    doctor_key: DoctorKey = None,
) -> DraftRead:
    """Дополнительный инструмент того же MCP-агента; старый v1 не изменяется."""
    response.headers["Cache-Control"] = "no-store"
    if len(await request.body()) > MAX_BODY_BYTES:
        raise HTTPException(413, "Превышен размер структурированных предложений")
    doctor = authenticate_site_doctor(db, doctor_key)
    patient_id = str(payload.patient_id)
    request_id = str(payload.request_id)
    require_site_request(db, doctor, patient_id, request_id)
    return import_structured_proposals(db, patient_id, doctor.id, request_id, payload)
