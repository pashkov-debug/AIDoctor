"""Проверка ограничений сохранения снимка без БД."""

from datetime import UTC, datetime

import pytest
from app.services.context_builder import ClinicalContext, ContextFact
from app.services.context_delta import calculate_content_sha256
from app.services.context_snapshots import SnapshotIntegrityError, _validate_current


def make_context() -> ClinicalContext:
    context = ClinicalContext(
        patient_id="synthetic-id",
        generated_at=datetime.now(UTC),
        items=[],
        excluded_attachments_count=0,
        content_sha256="0" * 64,
    )
    context.content_sha256 = calculate_content_sha256(context)
    return context


def test_valid_context_can_be_serialized():
    context = make_context()
    payload = _validate_current(context)
    assert payload["patient_id"] == "synthetic-id"
    assert payload["content_sha256"] == context.content_sha256


def test_truncated_context_cannot_be_saved():
    context = make_context()
    context.truncated_sources = ["observations"]
    context.content_sha256 = calculate_content_sha256(context)
    with pytest.raises(SnapshotIntegrityError, match="усечённый"):
        _validate_current(context)


def test_modified_hash_cannot_be_saved():
    context = make_context()
    context.content_sha256 = "f" * 64
    with pytest.raises(SnapshotIntegrityError, match="контрольная"):
        _validate_current(context)


def test_duplicate_fact_identity_rejected():
    context = make_context()
    fact = ContextFact(
        kind="history_event",
        record_id="same",
        at=datetime.now(UTC),
        source_ref="synthetic",
        payload={"text": "test"},
    )
    context.items = [fact, fact]
    context.content_sha256 = calculate_content_sha256(context)
    with pytest.raises(SnapshotIntegrityError, match="Повторяющиеся"):
        _validate_current(context)


def test_oversized_context_rejected():
    context = make_context()
    context.items = [
        ContextFact(
            kind="history_event",
            record_id="big",
            at=datetime.now(UTC),
            source_ref="synthetic",
            payload={"synthetic_text": "x" * (512 * 1024)},
        )
    ]
    context.content_sha256 = calculate_content_sha256(context)
    with pytest.raises(SnapshotIntegrityError, match="512"):
        _validate_current(context)
