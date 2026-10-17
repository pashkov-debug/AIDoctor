"""Детерминированная структурная сводка контекста — без медицинских выводов."""

from datetime import datetime
from typing import Literal

from app.services.context_builder import ClinicalContext, ContextFact
from pydantic import BaseModel

DIGEST_SCHEMA_VERSION = "1.0"
PREVIEW_LIMIT = 10
KINDS = ("encounter", "history_event", "observation", "questionnaire")


class DigestReference(BaseModel):
    kind: Literal["encounter", "history_event", "observation", "questionnaire"]
    record_id: str
    at: datetime
    source_ref: str


class ContextDigest(BaseModel):
    schema_version: Literal["1.0"] = DIGEST_SCHEMA_VERSION
    patient_id: str
    context_sha256: str
    generated_at: datetime
    total_facts: int
    counts_by_kind: dict[str, int]
    earliest_fact_at: datetime | None
    latest_fact_at: datetime | None
    latest_references: list[DigestReference]
    truncated_sources: list[str]
    excluded_attachments_count: int
    complete: bool


def _reference(fact: ContextFact) -> DigestReference:
    return DigestReference(
        kind=fact.kind,
        record_id=fact.record_id,
        at=fact.at,
        source_ref=fact.source_ref,
    )


def build_digest(context: ClinicalContext) -> ContextDigest:
    """Digest описывает состав снимка, не пытаясь обобщать клинические факты."""
    counts = {kind: 0 for kind in KINDS}
    for item in context.items:
        counts[item.kind] += 1

    ordered = sorted(
        context.items,
        key=lambda fact: (fact.at, fact.kind, fact.record_id),
        reverse=True,
    )
    return ContextDigest(
        patient_id=context.patient_id,
        context_sha256=context.content_sha256,
        generated_at=context.generated_at,
        total_facts=len(context.items),
        counts_by_kind=counts,
        earliest_fact_at=ordered[-1].at if ordered else None,
        latest_fact_at=ordered[0].at if ordered else None,
        latest_references=[_reference(fact) for fact in ordered[:PREVIEW_LIMIT]],
        truncated_sources=list(context.truncated_sources),
        excluded_attachments_count=context.excluded_attachments_count,
        complete=not context.truncated_sources,
    )
