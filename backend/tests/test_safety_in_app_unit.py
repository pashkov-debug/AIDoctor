"""Быстрые проверки 5.6 без соединения с PostgreSQL."""

from unittest.mock import Mock

import pytest
from app.core.config import settings
from app.db.metadata import metadata
from app.schemas.safety_in_app_notification import SafetyInAppNotificationRead
from app.services.safety_in_app_delivery import InAppTransport, list_own_inbox
from app.workers.safety_in_app_once import main as in_app_main
from app.workers.safety_outbox import TransportNotConfigured


def test_transport_denied_by_default():
    factory = Mock()
    with pytest.raises(TransportNotConfigured):
        InAppTransport(factory)
    factory.assert_not_called()


def test_cli_without_activation_does_not_open_session(monkeypatch):
    monkeypatch.setattr(settings, "safety_in_app_delivery_enabled", False)
    assert in_app_main([]) == 2
    assert in_app_main(["--once"]) == 2


def test_db_structure_and_no_medical_content_in_api_schema():
    assert "safety_in_app_notifications" in metadata.tables
    table = metadata.tables["safety_in_app_notifications"]
    assert {
        "id",
        "created_at",
        "outbox_id",
        "alert_id",
        "patient_id",
        "recipient_user_id",
        "route_id",
    } == set(table.columns.keys())
    assert set(SafetyInAppNotificationRead.model_fields) == {
        "id",
        "patient_id",
        "alert_id",
        "created_at",
    }


def test_get_inbox_limit_rejected_before_query():
    session = Mock()
    with pytest.raises(ValueError):
        list_own_inbox(session, recipient_user_id="x", limit=0)
    with pytest.raises(ValueError):
        list_own_inbox(session, recipient_user_id="x", limit=101)
    session.scalars.assert_not_called()
