"""Этап 5.3: локальные проверки ключей/метаданных без PostgreSQL."""

import pytest
from app.db.metadata import metadata
from app.schemas.safety_alert import SafetyAlertCreate
from app.services.safety_alerts import (
    InvalidIdempotencyKey,
    alert_request_digest,
    idempotency_key_digest,
)


@pytest.mark.parametrize(
    "value",
    [
        "", "short", "bad space1", "é" * 8, "A" * 129,
        "\\nheader_injection", "key/with/slash", "ABC\t12345",
    ],
)
def test_rejects_invalid_keys(value):
    with pytest.raises(InvalidIdempotencyKey):
        idempotency_key_digest(value)


@pytest.mark.parametrize(
    "value",
    ["12345678", "550e8400-e29b-41d4-a716-446655440000", "key.test:2026"],
)
def test_valid_keys_are_digest_only(value):
    digest = idempotency_key_digest(value)
    assert len(digest) == 64
    assert value not in digest
    assert digest == idempotency_key_digest(value)


def test_body_digest_is_stable_and_distinct_for_different_fields():
    baseline = SafetyAlertCreate(reason_code="clinician_review", priority="standard")
    equivalent = SafetyAlertCreate(priority="standard", reason_code="clinician_review")
    changed = SafetyAlertCreate(reason_code="clinician_review", priority="urgent")
    assert alert_request_digest(baseline) == alert_request_digest(equivalent)
    assert alert_request_digest(baseline) != alert_request_digest(changed)


def test_request_metadata_is_registered_and_references_alert():
    assert "safety_alert_requests" in metadata.tables
    table = metadata.tables["safety_alert_requests"]
    assert table.c.alert_id.nullable is False
    assert table.c.actor_id.nullable is False
    assert table.c.patient_id.nullable is False
    assert table.c.key_digest.nullable is False
    assert table.c.key_digest.type.length == 64
