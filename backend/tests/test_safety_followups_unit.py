"""Unit-проверки 5.7: без PostgreSQL."""

from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from app.core.config import settings
from app.db.metadata import metadata
from app.schemas.safety_followup import SafetyFollowupRead
from app.services.safety_followups import (
    FOLLOWUP_AFTER_HOURS,
    FOLLOWUP_WINDOW_HOURS,
    MAX_FOLLOWUPS_PER_DOCTOR_WINDOW,
    create_one_due_followup,
    list_own_open_followups,
)
from app.workers.safety_followup_once import main


def test_disabled_cli_does_not_open_database(monkeypatch):
    monkeypatch.setattr(settings, "safety_followup_scan_enabled", False)
    assert main([]) == 2
    assert main(["--once"]) == 2


def test_schema_and_metadata_have_no_clinical_text():
    table = metadata.tables["safety_followups"]
    assert set(table.columns.keys()) == {
        "id", "created_at", "alert_id", "patient_id", "recipient_user_id", "route_id"
    }
    assert set(SafetyFollowupRead.model_fields) == {
        "id", "patient_id", "alert_id", "created_at"
    }


def test_policy_constants():
    assert FOLLOWUP_AFTER_HOURS == FOLLOWUP_WINDOW_HOURS == 24
    assert MAX_FOLLOWUPS_PER_DOCTOR_WINDOW == 5


def test_validation_before_db():
    session = Mock()
    with pytest.raises(ValueError):
        create_one_due_followup(session, now=datetime(2026, 10, 18))
    with pytest.raises(ValueError):
        list_own_open_followups(session, recipient_user_id="x", limit=0)
    with pytest.raises(ValueError):
        list_own_open_followups(session, recipient_user_id="x", limit=101)
    session.scalars.assert_not_called()


def test_timezone_accepted_by_validation(monkeypatch):
    from app.services import safety_followups

    assert safety_followups._moment(datetime(2026, 10, 18, tzinfo=UTC)).tzinfo == UTC
