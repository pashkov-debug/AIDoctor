"""Без PostgreSQL: только схемы, контракт и регистрация роутера."""

import pytest
from app.db.metadata import metadata
from app.schemas.safety_notification_route import NotificationRouteChange
from app.services.safety_notification_routes import EligibleRoute
from fastapi.testclient import TestClient
from pydantic import ValidationError


def test_schema_accepts_only_internal_channel_and_boolean():
    assert NotificationRouteChange(enabled=False).channel == "in_app"
    with pytest.raises(ValidationError):
        NotificationRouteChange(enabled=True, channel="email")
    with pytest.raises(ValidationError):
        NotificationRouteChange(enabled=True, recipient_user_id="other")
    with pytest.raises(ValidationError):
        NotificationRouteChange(enabled="maybe")


def test_model_constraints_and_audit_exist():
    routes = metadata.tables["safety_notification_routes"]
    events = metadata.tables["safety_notification_route_events"]
    assert "confirmed_at" in routes.c
    assert "enabled" in routes.c
    assert "route_id" in events.c
    names = {item.name for item in routes.constraints}
    assert "uq_safety_notification_routes_scope" in names
    assert "ck_safety_notification_routes_confirmation" in names


def test_route_object_contains_no_patient_or_contact_details():
    result = EligibleRoute("route", "doctor", "in_app")
    assert not hasattr(result, "patient_id")
    assert not hasattr(result, "email")
    assert not hasattr(result, "phone")


def test_route_api_registered_once_and_auth_required():
    pytest.importorskip("psycopg")
    from app.main import create_app

    application = create_app()
    path = "/api/v1/patients/{patient_id}/safety-notification-route"
    schema = application.openapi()
    assert {"get", "put"} <= set(schema["paths"][path])
    assert list(schema["paths"]).count(path) == 1
    with TestClient(application) as client:
        actual = "/api/v1/patients/not-found/safety-notification-route"
        assert client.get(actual).status_code == 401
        assert client.put(actual, json={"enabled": True}).status_code == 401
