"""Unit: валидация и fail-closed без подключения PostgreSQL."""

from unittest.mock import Mock

import pytest
from app.db.metadata import metadata
from app.models.safety_read_audit import SafetyReadAudit
from app.services.safety_read_audit import record_safety_read
from sqlalchemy import CheckConstraint


def test_only_technical_fields_are_persisted():
    table = metadata.tables["safety_read_audit"]
    assert set(table.columns.keys()) == {
        "id",
        "created_at",
        "actor_id",
        "patient_id",
        "scope",
        "returned_count",
    }
    assert any(isinstance(item, CheckConstraint) for item in table.constraints)
    assert "text" not in table.columns
    assert "payload" not in table.columns


@pytest.mark.parametrize(
    ("scope", "patient_id", "count"),
    [
        ("unknown", None, 0),
        ("alerts_list", None, 1),
        ("route_read", None, 0),
        ("inbox_list", "patient", 0),
        ("followups_list", "patient", 0),
        ("inbox_list", None, -1),
        ("inbox_list", None, 101),
        ("inbox_list", None, True),
    ],
)
def test_invalid_values_dont_touch_session(scope, patient_id, count):
    session = Mock()
    with pytest.raises(ValueError):
        record_safety_read(
            session,
            actor_id="doctor",
            scope=scope,
            patient_id=patient_id,
            returned_count=count,
        )
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_missing_actor_rejected():
    session = Mock()
    with pytest.raises(ValueError):
        record_safety_read(session, actor_id=" ", scope="inbox_list", returned_count=0)
    session.add.assert_not_called()


def test_successful_read_commits_minimal_record():
    session = Mock()
    record_safety_read(
        session,
        actor_id="doctor",
        scope="alerts_list",
        patient_id="patient",
        returned_count=12,
    )
    obj = session.add.call_args.args[0]
    assert isinstance(obj, SafetyReadAudit)
    assert (obj.actor_id, obj.patient_id, obj.scope, obj.returned_count) == (
        "doctor",
        "patient",
        "alerts_list",
        12,
    )
    session.commit.assert_called_once()


def test_failed_commit_rolls_back_and_raises():
    session = Mock()
    session.commit.side_effect = RuntimeError("db down")
    with pytest.raises(RuntimeError, match="db down"):
        record_safety_read(session, actor_id="doctor", scope="inbox_list", returned_count=0)
    session.rollback.assert_called_once()
