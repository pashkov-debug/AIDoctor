"""Версионирование готового медицинского контекста в PostgreSQL.

Сервис намеренно не проверяет права: разрешения всегда проверяет API ДО вызова.
"""

import hmac
import json
from datetime import datetime

from app.models.context_snapshot import ContextSnapshot
from app.services.context_builder import ClinicalContext
from app.services.context_delta import (
    MAX_SNAPSHOT_FACTS,
    calculate_content_sha256,
)
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

MAX_SNAPSHOT_BYTES = 512 * 1024
LIST_LIMIT = 50


class SnapshotNotFoundError(LookupError):
    """Снимок не принадлежит пациенту либо отсутствует."""


class SnapshotIntegrityError(ValueError):
    """Запись повреждена или нарушен контракт проверки снимка."""


class SnapshotSummary(BaseModel):
    id: str
    patient_id: str
    created_at: datetime
    created_by_id: str
    schema_version: str
    content_sha256: str
    fact_count: int


class SnapshotWithContext(BaseModel):
    snapshot: SnapshotSummary
    context: ClinicalContext


def _summary(row: ContextSnapshot) -> SnapshotSummary:
    return SnapshotSummary(
        id=row.id,
        patient_id=row.patient_id,
        created_at=row.created_at,
        created_by_id=row.created_by_id,
        schema_version=row.schema_version,
        content_sha256=row.content_sha256,
        fact_count=row.fact_count,
    )


def _validate_current(context: ClinicalContext) -> dict:
    if context.schema_version != "1.0":
        raise SnapshotIntegrityError("Неподдерживаемая версия контекста")
    if context.truncated_sources:
        raise SnapshotIntegrityError("Нельзя сохранять усечённый контекст")
    if len(context.items) > MAX_SNAPSHOT_FACTS:
        raise SnapshotIntegrityError("Превышен лимит записей")
    actual = calculate_content_sha256(context)
    if not hmac.compare_digest(context.content_sha256, actual):
        raise SnapshotIntegrityError("Некорректная контрольная сумма")
    keys = [(fact.kind, fact.record_id) for fact in context.items]
    if len(keys) != len(set(keys)):
        raise SnapshotIntegrityError("Повторяющиеся записи в снимке")
    payload = context.model_dump(mode="json", exclude_none=False)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise SnapshotIntegrityError("Размер снимка превышает лимит 512 КиБ")
    return payload


def create_snapshot(
    session: Session, context: ClinicalContext, created_by_id: str
) -> SnapshotSummary:
    payload = _validate_current(context)
    row = ContextSnapshot(
        patient_id=context.patient_id,
        created_by_id=created_by_id,
        schema_version=context.schema_version,
        content_sha256=context.content_sha256,
        fact_count=len(context.items),
        payload_json=payload,
    )
    session.add(row)
    try:
        session.commit()
        session.refresh(row)
    except Exception:
        session.rollback()
        raise
    return _summary(row)


def list_snapshots(session: Session, patient_id: str) -> list[SnapshotSummary]:
    rows = session.scalars(
        select(ContextSnapshot)
        .where(ContextSnapshot.patient_id == patient_id)
        .order_by(ContextSnapshot.created_at.desc(), ContextSnapshot.id.desc())
        .limit(LIST_LIMIT)
    ).all()
    return [_summary(row) for row in rows]


def get_snapshot(session: Session, patient_id: str, snapshot_id: str) -> SnapshotWithContext:
    row = session.scalar(
        select(ContextSnapshot).where(
            ContextSnapshot.id == snapshot_id,
            ContextSnapshot.patient_id == patient_id,
        )
    )
    if row is None:
        raise SnapshotNotFoundError(snapshot_id)
    try:
        context = ClinicalContext.model_validate(row.payload_json)
        _validate_current(context)
        if (
            context.patient_id != patient_id
            or context.schema_version != row.schema_version
            or not hmac.compare_digest(context.content_sha256, row.content_sha256)
            or len(context.items) != row.fact_count
        ):
            raise SnapshotIntegrityError("Метаданные снимка не соответствуют содержимому")
    except (ValueError, TypeError) as exc:
        raise SnapshotIntegrityError("Снимок повреждён или несовместим") from exc
    return SnapshotWithContext(snapshot=_summary(row), context=context)
