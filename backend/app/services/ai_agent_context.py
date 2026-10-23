"""Неизменяемая выборка утверждённых назначений и врачебных черновиков.

Права проверяет маршрут API; сервис не выполняет внешних запросов.
"""

import hashlib
import hmac
import json
from typing import Any

from app.models.ai_workspace import AIRequest
from app.models.clinical_order import ClinicalOrder
from app.schemas.ai_agent_context import AIAgentContextRead, OrdersReviewSnapshot
from app.services.context_snapshots import (
    SnapshotIntegrityError,
    SnapshotNotFoundError,
    get_snapshot,
)
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

MAX_REVIEW_ORDERS = 100
MAX_REVIEW_BYTES = 256 * 1024
ORDER_FIELDS = (
    "id",
    "version",
    "status",
    "kind",
    "name",
    "active_ingredient",
    "dosage_form",
    "strength",
    "dose_value",
    "dose_unit",
    "route",
    "frequency_per_day",
    "times_local",
    "timezone",
    "start_date",
    "duration_days",
    "administration_notes",
    "examination_details",
    "indication",
    "contraindications",
    "rationale",
    "source_reference",
)


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def review_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _serialise_order(order: ClinicalOrder) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in ORDER_FIELDS:
        value = getattr(order, key)
        if key == "dose_value":
            value = str(value) if value is not None else None
        elif key == "start_date":
            value = value.isoformat() if value is not None else None
        values[key] = value
    return values


def build_orders_review(db: Session, patient_id: str) -> dict[str, Any]:
    """Не усекает списки: превышение лимита запрещает подготовку запроса."""
    rows = db.scalars(
        select(ClinicalOrder)
        .where(
            ClinicalOrder.patient_id == patient_id,
            ClinicalOrder.status.in_(("draft", "approved")),
        )
        .order_by(ClinicalOrder.id)
        .limit(MAX_REVIEW_ORDERS + 1)
    ).all()
    if len(rows) > MAX_REVIEW_ORDERS:
        raise HTTPException(409, "Слишком много назначений для полного снимка проверки")
    payload = {
        "schema_version": "orders_for_ai_review.v1",
        "approved_orders": [_serialise_order(row) for row in rows if row.status == "approved"],
        "proposed_orders_for_review": [
            _serialise_order(row) for row in rows if row.status == "draft"
        ],
        "draft_orders_are_not_treatment": True,
        "clinical_safety_validated": False,
    }
    validated = OrdersReviewSnapshot.model_validate(payload).model_dump(mode="json")
    if len(_canonical(validated)) > MAX_REVIEW_BYTES:
        raise HTTPException(409, "Снимок назначений превышает безопасный лимит")
    return validated


def current_orders_match(db: Session, request: AIRequest) -> bool:
    """Для старых запросов проверка недоступна; их контекст не подменяется."""
    if request.review_orders_json is None or request.review_orders_sha256 is None:
        return True  # старый UI-4A контракт не меняем задним числом
    original = review_hash(request.review_orders_json)
    if not hmac.compare_digest(original, request.review_orders_sha256):
        raise HTTPException(409, "Контрольная сумма сохранённых назначений повреждена")
    current = build_orders_review(db, request.patient_id)
    return hmac.compare_digest(review_hash(current), original)


def get_agent_context(
    db: Session,
    doctor_id: str,
    patient_id: str,
    request_id: str,
) -> AIAgentContextRead:
    request = db.scalar(
        select(AIRequest).where(
            AIRequest.id == request_id,
            AIRequest.doctor_id == doctor_id,
            AIRequest.patient_id == patient_id,
        )
    )
    if request is None:
        raise HTTPException(404, "AI-запрос не найден")
    if request.review_orders_json is None or request.review_orders_sha256 is None:
        raise HTTPException(
            409,
            "Запрос создан до фиксации проектов назначений. Создайте новый AI-запрос.",
        )
    try:
        orders = OrdersReviewSnapshot.model_validate(request.review_orders_json)
        actual = review_hash(orders.model_dump(mode="json"))
        if not hmac.compare_digest(actual, request.review_orders_sha256):
            raise HTTPException(409, "Снимок проектов назначений повреждён")
        source = get_snapshot(db, patient_id, request.context_snapshot_id).context
        if not hmac.compare_digest(source.content_sha256, request.context_sha256):
            raise HTTPException(409, "Контекст пациента не соответствует AI-запросу")
    except (ValueError, TypeError, SnapshotIntegrityError, SnapshotNotFoundError) as exc:
        raise HTTPException(409, "Снимок контекста повреждён или недоступен") from exc
    # Непроверенные документы никогда не входят в клинический контекст.
    return AIAgentContextRead(
        request_id=request.id,
        patient_id=patient_id,
        doctor_id=doctor_id,
        question=request.question,
        created_at=request.created_at,
        patient_context=source,
        doctor_context=request.doctor_context_json,
        orders_review=orders,
        orders_sha256=request.review_orders_sha256,
        excluded_attachments=request.attachment_manifest_json,
    )
