"""Интеграционные PostgreSQL-тесты маршрутов безопасности."""

from collections.abc import Iterator

import pytest
from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from app.models.safety_alert import SafetyAlert, SafetyAlertEvent
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.fixture
def safety_api(pg_engine) -> Iterator[tuple[TestClient, dict[str, str]]]:
    with Session(pg_engine) as session:
        doctor = User(username="safety-doctor", password_hash="x", role="doctor")
        stranger = User(username="safety-stranger", password_hash="x", role="doctor")
        patient_user = User(username="safety-patient", password_hash="x", role="patient")
        session.add_all([doctor, stranger, patient_user])
        session.flush()
        patient = Patient(
            alias="SYNTHETIC-SAFETY", user_id=patient_user.id, demographics_json={}
        )
        another_patient = Patient(alias="SYNTHETIC-OTHER", demographics_json={})
        session.add_all([patient, another_patient])
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        state = {
            "doctor": doctor.id,
            "stranger": stranger.id,
            "patient_user": patient_user.id,
            "patient": patient.id,
            "other_patient": another_patient.id,
            "active": doctor.id,
        }
        session.commit()

    def override_session():
        with Session(pg_engine) as session:
            yield session

    def override_user():
        with Session(pg_engine) as session:
            return session.get(User, state["active"])

    application = create_app()
    application.dependency_overrides[get_db] = override_session
    application.dependency_overrides[current_user] = override_user
    try:
        with TestClient(application) as client:
            yield client, state
    finally:
        application.dependency_overrides.clear()


def test_create_ack_idempotent_and_audited(safety_api, pg_engine):
    client, state = safety_api
    url = f"/api/v1/patients/{state['patient']}/safety-alerts"
    created = client.post(
        url, json={"reason_code": "clinician_review", "priority": "standard"}
    )
    assert created.status_code == 201, created.text
    item = created.json()
    assert item["status"] == "open"
    assert item["delivery_status"] == "not_configured"
    assert item["created_by_id"] == state["doctor"]
    assert client.get(url).json()[0]["id"] == item["id"]

    confirmed = client.post(f"{url}/{item['id']}/ack")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "acknowledged"
    assert confirmed.json()["acknowledged_by_id"] == state["doctor"]
    assert confirmed.json()["acknowledged_at"]

    repeated = client.post(f"{url}/{item['id']}/ack")
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["acknowledged_at"] == confirmed.json()["acknowledged_at"]

    with Session(pg_engine) as session:
        assert session.scalar(select(SafetyAlert).where(SafetyAlert.id == item["id"]))
        events = session.scalars(
            select(SafetyAlertEvent)
            .where(SafetyAlertEvent.alert_id == item["id"])
            .order_by(SafetyAlertEvent.created_at)
        ).all()
        assert sorted(event.event_type for event in events) == [
            "acknowledged",
            "created",
        ]


def test_stranger_cannot_discover_patient_or_create(safety_api):
    client, state = safety_api
    url = f"/api/v1/patients/{state['patient']}/safety-alerts"
    state["active"] = state["stranger"]
    assert client.get(url).status_code == 404
    assert client.post(
        url, json={"reason_code": "unknown", "priority": "untrusted"}
    ).status_code == 404
    assert client.post(f"{url}/does-not-exist/ack").status_code == 404


def test_patient_cannot_use_internal_clinician_alerts(safety_api):
    client, state = safety_api
    state["active"] = state["patient_user"]
    url = f"/api/v1/patients/{state['patient']}/safety-alerts"
    assert client.get(url).status_code == 403
    assert client.post(
        url, json={"reason_code": "urgent_attention", "priority": "urgent"}
    ).status_code == 403


def test_invalid_payload_does_not_create_alert(safety_api):
    client, state = safety_api
    url = f"/api/v1/patients/{state['patient']}/safety-alerts"
    response = client.post(
        url, json={"reason_code": "unknown", "priority": "urgent"}
    )
    assert response.status_code == 422
    assert client.get(url).json() == []


def test_cross_patient_alert_id_is_not_accessible(safety_api):
    client, state = safety_api
    url = f"/api/v1/patients/{state['patient']}/safety-alerts"
    created = client.post(
        url, json={"reason_code": "urgent_attention", "priority": "urgent"}
    )
    alert_id = created.json()["id"]
    other = f"/api/v1/patients/{state['other_patient']}/safety-alerts"
    assert client.post(f"{other}/{alert_id}/ack").status_code == 404


def test_unauthenticated_requests_get_401():
    with TestClient(create_app()) as client:
        url = "/api/v1/patients/nonexistent/safety-alerts"
        assert client.get(url).status_code == 401
        assert client.post(
            url, json={"reason_code": "clinician_review", "priority": "standard"}
        ).status_code == 401
        assert client.post(f"{url}/nonexistent/ack").status_code == 401
