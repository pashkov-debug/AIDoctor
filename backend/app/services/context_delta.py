"""Сравнение двух снимков контекста. Клиентский baseline не является доверенным архивом."""

import hashlib
import hmac
import json
from typing import Literal

from app.services.context_builder import ClinicalContext, ContextFact
from pydantic import BaseModel

DELTA_SCHEMA_VERSION = "1.0"
MAX_SNAPSHOT_FACTS = 400


class SnapshotValidationError(ValueError):
    """Некорректный либо неполный базовый снимок."""


class FactIdentity(BaseModel):
    kind: Literal["encounter", "history_event", "observation", "questionnaire"]
    record_id: str


class ContextDelta(BaseModel):
    schema_version: Literal["1.0"] = DELTA_SCHEMA_VERSION
    patient_id: str
    from_sha256: str
    to_sha256: str
    changed: bool
    added: list[ContextFact]
    updated: list[ContextFact]
    removed: list[FactIdentity]
    attachments_count_change: int
    before_fact_count: int
    after_fact_count: int


def calculate_content_sha256(context: ClinicalContext) -> str:
    """Точное правило хэширования из ContextBuilder v1; generated_at исключён."""
    canonical = json.dumps(
        {
            "schema_version": context.schema_version,
            "patient_id": context.patient_id,
            "items": [item.model_dump(mode="json", exclude_none=False) for item in context.items],
            "truncated_sources": context.truncated_sources,
            "excluded_attachments_count": context.excluded_attachments_count,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _items_by_key(
    context: ClinicalContext,
) -> dict[tuple[str, str], ContextFact]:
    found: dict[tuple[str, str], ContextFact] = {}
    for fact in context.items:
        key = (fact.kind, fact.record_id)
        if key in found:
            raise SnapshotValidationError("Повторяющийся идентификатор записи в снимке")
        found[key] = fact
    return found


def _check_snapshot(context: ClinicalContext, patient_id: str) -> None:
    if context.schema_version != "1.0":
        raise SnapshotValidationError("Неподдерживаемая версия контекста")
    if context.patient_id != patient_id:
        raise SnapshotValidationError("Контекст относится к другому пациенту")
    if context.truncated_sources:
        raise SnapshotValidationError("Нельзя сравнивать усечённый снимок")
    if len(context.items) > MAX_SNAPSHOT_FACTS:
        raise SnapshotValidationError("Снимок превышает лимит записей")
    if not hmac.compare_digest(context.content_sha256, calculate_content_sha256(context)):
        raise SnapshotValidationError("Контрольная сумма контекста не совпадает")
    _items_by_key(context)


def _fact_value(fact: ContextFact) -> dict:
    return fact.model_dump(mode="json", exclude_none=False)


def compare_contexts(
    baseline: ClinicalContext,
    current: ClinicalContext,
) -> ContextDelta:
    """Сопоставление записей по kind+record_id; исправления могут означать remove+add.

    SHA-256 доказывает только отсутствие случайного расхождения внутри переданного
    снимка. Клиент способен пересчитать хэш; происхождение baseline не проверяется.
    """
    _check_snapshot(baseline, current.patient_id)
    _check_snapshot(current, current.patient_id)

    before = _items_by_key(baseline)
    after = _items_by_key(current)
    added = [after[key] for key in after.keys() - before.keys()]
    removed = [FactIdentity(kind=key[0], record_id=key[1]) for key in before.keys() - after.keys()]
    updated = [
        after[key]
        for key in before.keys() & after.keys()
        if _fact_value(before[key]) != _fact_value(after[key])
    ]
    added.sort(key=lambda fact: (fact.at, fact.kind, fact.record_id))
    updated.sort(key=lambda fact: (fact.at, fact.kind, fact.record_id))
    removed.sort(key=lambda fact: (fact.kind, fact.record_id))
    return ContextDelta(
        patient_id=current.patient_id,
        from_sha256=baseline.content_sha256,
        to_sha256=current.content_sha256,
        changed=baseline.content_sha256 != current.content_sha256,
        added=added,
        updated=updated,
        removed=removed,
        attachments_count_change=(
            current.excluded_attachments_count - baseline.excluded_attachments_count
        ),
        before_fact_count=len(before),
        after_fact_count=len(after),
    )
