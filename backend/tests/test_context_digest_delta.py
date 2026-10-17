"""Unit-тесты для структурного Digest и сравнения снимков Context Builder."""

from datetime import UTC, datetime, timedelta

import pytest
from app.services.context_builder import ClinicalContext, ContextFact
from app.services.context_delta import (
    SnapshotValidationError,
    calculate_content_sha256,
    compare_contexts,
)
from app.services.context_digest import build_digest


def fact(
    kind: str = "history_event",
    record_id: str = "a",
    text: str = "synthetic fact",
) -> ContextFact:
    return ContextFact(
        kind=kind,
        record_id=record_id,
        at=datetime(2026, 1, 1, tzinfo=UTC),
        source_ref=f"test:{record_id}",
        payload={"text": text},
    )


def snapshot(
    items: list[ContextFact] | None = None,
    *,
    patient_id: str = "patient-1",
    truncated: list[str] | None = None,
    attachments: int = 0,
) -> ClinicalContext:
    model = ClinicalContext(
        patient_id=patient_id,
        generated_at=datetime(2026, 2, 1, tzinfo=UTC),
        items=items if items is not None else [],
        truncated_sources=truncated or [],
        excluded_attachments_count=attachments,
        content_sha256="0" * 64,
    )
    model.content_sha256 = calculate_content_sha256(model)
    return model


def test_digest_empty_and_deterministic():
    model = snapshot()
    digest = build_digest(model)
    assert digest.complete
    assert digest.total_facts == 0
    assert digest.earliest_fact_at is None
    assert digest.latest_fact_at is None
    assert set(digest.counts_by_kind.values()) == {0}
    assert digest.latest_references == []


def test_digest_counts_truncation_and_no_payload():
    model = snapshot(
        [fact(), fact("observation", "b")],
        truncated=["questionnaires"],
        attachments=3,
    )
    digest = build_digest(model)
    assert digest.total_facts == 2
    assert digest.counts_by_kind["history_event"] == 1
    assert digest.counts_by_kind["observation"] == 1
    assert digest.complete is False
    assert digest.excluded_attachments_count == 3
    assert "synthetic fact" not in digest.model_dump_json()


def test_delta_identical_snapshots():
    model = snapshot([fact()])
    other = model.model_copy(deep=True)
    other.generated_at += timedelta(days=1)
    result = compare_contexts(model, other)
    assert not result.changed
    assert not result.added
    assert not result.updated
    assert not result.removed


def test_delta_added_updated_removed_and_attachment_metadata():
    before = snapshot([fact(record_id="gone"), fact(record_id="edited")])
    after = snapshot(
        [fact(record_id="edited", text="corrected"), fact(record_id="new")],
        attachments=2,
    )
    result = compare_contexts(before, after)
    assert result.changed
    assert [x.record_id for x in result.added] == ["new"]
    assert [x.record_id for x in result.updated] == ["edited"]
    assert [x.record_id for x in result.removed] == ["gone"]
    assert result.attachments_count_change == 2


def test_delta_only_attachment_count_changed():
    before = snapshot(attachments=1)
    after = snapshot(attachments=2)
    result = compare_contexts(before, after)
    assert result.changed
    assert result.attachments_count_change == 1
    assert result.added == result.updated == result.removed == []


@pytest.mark.parametrize("mode", ["patient", "hash", "truncated", "duplicate", "too_many"])
def test_reject_invalid_or_incomplete_baseline(mode):
    baseline = snapshot([fact()])
    current = snapshot([fact()])
    if mode == "patient":
        baseline.patient_id = "another-patient"
    elif mode == "hash":
        baseline.items[0].payload["text"] = "unverified modification"
    elif mode == "truncated":
        baseline = snapshot([fact()], truncated=["encounters"])
    elif mode == "duplicate":
        baseline = snapshot([fact(), fact()])
    else:
        baseline = snapshot([fact(record_id=str(i)) for i in range(401)])
    with pytest.raises(SnapshotValidationError):
        compare_contexts(baseline, current)


def test_reject_truncated_current_even_if_baseline_complete():
    with pytest.raises(SnapshotValidationError, match="усечённый"):
        compare_contexts(snapshot(), snapshot(truncated=["observations"]))


def test_changed_fact_uses_record_identity_and_source_metadata():
    before = snapshot([fact("observation", "id", "one")])
    after = snapshot([fact("observation", "id", "two")])
    result = compare_contexts(before, after)
    assert result.changed
    assert len(result.updated) == 1
    assert result.updated[0].source_ref == "test:id"
