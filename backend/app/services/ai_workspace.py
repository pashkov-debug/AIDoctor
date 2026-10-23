"""Атомарная фиксация запроса, клинического snapshot и аудита.

Здесь принципиально отсутствует сетевой вызов LLM и создание AI-черновика.
"""

from app.models.ai_workspace import AIRequest, AIRequestAudit
from app.models.context_snapshot import ContextSnapshot
from app.models.medical_record import MedicalAttachment
from app.schemas.ai_workspace import AIRequestCreate, AIRequestRead
from app.services.context_builder import ContextBuilder
from app.services.context_snapshots import SnapshotIntegrityError, _validate_current
from app.services.doctor_settings import read_doctor_context
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

MAX_REQUESTS = 50


def _result(row: AIRequest) -> AIRequestRead:
    return AIRequestRead(
        id=row.id,
        patient_id=row.patient_id,
        doctor_id=row.doctor_id,
        request_key=row.request_key,
        schema_version=row.schema_version,
        question=row.question,
        created_at=row.created_at,
        context_snapshot_id=row.context_snapshot_id,
        context_sha256=row.context_sha256,
        doctor_context=row.doctor_context_json,
        attachment_manifest=row.attachment_manifest_json,
    )


def list_requests(db: Session, doctor_id: str, patient_id: str) -> list[AIRequestRead]:
    rows = db.scalars(
        select(AIRequest)
        .where(AIRequest.doctor_id == doctor_id, AIRequest.patient_id == patient_id)
        .order_by(AIRequest.created_at.desc(), AIRequest.id.desc())
        .limit(MAX_REQUESTS)
    ).all()
    return [_result(item) for item in rows]


def get_request(db: Session, doctor_id: str, patient_id: str, request_id: str) -> AIRequestRead:
    row = db.scalar(
        select(AIRequest).where(
            AIRequest.id == request_id,
            AIRequest.patient_id == patient_id,
            AIRequest.doctor_id == doctor_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Запрос не найден")
    return _result(row)


def create_request(
    db: Session, doctor_id: str, patient_id: str, payload: AIRequestCreate
) -> AIRequestRead:
    key = str(payload.request_key)
    ids = [str(value) for value in payload.attachment_ids]
    existing = db.scalar(
        select(AIRequest).where(AIRequest.doctor_id == doctor_id, AIRequest.request_key == key)
    )
    if existing is not None:
        if (
            existing.patient_id != patient_id
            or existing.question != payload.question
            or [item["id"] for item in existing.attachment_manifest_json] != ids
        ):
            raise HTTPException(status_code=409, detail="Ключ запроса уже использован")
        return _result(existing)
    manifest = []
    if ids:
        attachments = db.scalars(
            select(MedicalAttachment).where(
                MedicalAttachment.patient_id == patient_id,
                MedicalAttachment.id.in_(ids),
            )
        ).all()
        by_id = {item.id: item for item in attachments}
        if len(by_id) != len(ids):
            raise HTTPException(status_code=404, detail="Вложение не найдено у пациента")
        manifest = [
            {
                "id": item_id,
                "filename": by_id[item_id].filename,
                "content_sha256": by_id[item_id].content_sha256,
                "status": "excluded_unverified",
            }
            for item_id in ids
        ]
    try:
        current = ContextBuilder(db).build(patient_id)
        snapshot_payload = _validate_current(current)
        doctor_context = read_doctor_context(db, doctor_id).model_dump(mode="json")
        snapshot = ContextSnapshot(
            patient_id=patient_id,
            created_by_id=doctor_id,
            schema_version=current.schema_version,
            content_sha256=current.content_sha256,
            fact_count=len(current.items),
            payload_json=snapshot_payload,
        )
        db.add(snapshot)
        db.flush()
        row = AIRequest(
            patient_id=patient_id,
            doctor_id=doctor_id,
            request_key=key,
            schema_version="ai_request.v1",
            question=payload.question,
            context_snapshot_id=snapshot.id,
            context_sha256=current.content_sha256,
            doctor_context_json=doctor_context,
            attachment_manifest_json=manifest,
            status="prepared",
            revision=1,
        )
        db.add(row)
        db.flush()
        db.add(AIRequestAudit(request_id=row.id, actor_id=doctor_id, event="prepared"))
        db.commit()
        db.refresh(row)
        return _result(row)
    except SnapshotIntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail=f"Невозможно зафиксировать контекст: {exc}"
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Конфликт ключа запроса; обновите список"
        ) from exc
    except Exception:
        db.rollback()
        raise
