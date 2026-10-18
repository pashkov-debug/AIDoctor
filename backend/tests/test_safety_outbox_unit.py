"""Локальные проверки алгоритма Outbox без реальной БД."""

from datetime import datetime

import pytest
from app.db.metadata import metadata
from app.services.safety_outbox import (
    OutboxClaim,
    _now_or_raise,
    mark_attempt_failed,
    retry_delay_seconds,
)


def test_retry_backoff_and_bounds():
    assert [retry_delay_seconds(i) for i in (1, 2, 3)] == [30, 60, 120]
    with pytest.raises(ValueError):
        retry_delay_seconds(0)
    with pytest.raises(ValueError):
        retry_delay_seconds(4)


def test_clock_must_be_timezone_aware():
    with pytest.raises(ValueError, match="часовой пояс"):
        _now_or_raise(datetime(2026, 10, 18))


@pytest.mark.parametrize("code", ["", "A", "raw diagnostic text", "password=secret", "x" * 49])
def test_error_codes_reject_arbitrary_text(code):
    claim = OutboxClaim("outbox", "alert", "created", "token", 1)
    with pytest.raises(ValueError, match="error_code"):
        mark_attempt_failed(None, claim, error_code=code)


def test_models_registered_in_common_metadata():
    assert "safety_alerts" in metadata.tables
    assert "safety_alert_events" in metadata.tables
    assert "safety_outbox" in metadata.tables
    assert "safety_outbox_events" in metadata.tables
    columns = metadata.tables["safety_outbox"].c
    assert columns.alert_id.nullable is False
    assert columns.next_attempt_at.nullable is False
