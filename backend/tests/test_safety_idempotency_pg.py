"""Интеграционные тесты идемпотентности: требуется отдельная локальная *_test PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from app.models.safety_alert import SafetyAlert, SafetyAlertEvent
from app.models.safety_alert_request import SafetyAlertRequest
from app.models.safety_outbox import SafetyOutbox, SafetyOutboxEvent
from app.schemas.safety_alert import SafetyAlertCreate
from app.services.safety_alerts import IdempotencyConflict, create_alert
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


@pytest.fixture
def api(pg_engine):
    with Session(pg_engine) as session:
        first = User(username="idem-doctor-1", password_hash="x", role="doctor")
        second = User(username="idem-doctor-2", password_hash="x", role="doctor")
        stranger = User(username="idem-stranger", password_hash="x", role="doctor")
        patient_user = User(username="idem-patient", password_hash="x", role="patient")
        session.add_all((first, second, stranger, patient_user))
        session.flush()
        patient = Patient(alias="SYNTHETIC-IDEM", user_id=patient_user.id, demographics_json={})
        other = Patient(alias="SYNTHETIC-IDEM-2", demographics_json={})
        session.add_all((patient, other))
        session.flush()
        session.add_all(
            (
                DoctorPatient(doctor_id=first.id, patient_id=patient.id),
                DoctorPatient(doctor_id=first.id, patient_id=other.id),
                DoctorPatient(doctor_id=second.id, patient_id=patient.id),
            )
        )
        state = {
            "first": first.id,
            "second": second.id,
            "stranger": stranger.id,
            "patient_user": patient_user.id,
            "patient": patient.id,
            "other": other.id,
            "active": first.id,
        }
        session.commit()

    def session_override():
        with Session(pg_engine) as session:
            yield session

    def user_override():
        with Session(pg_engine) as session:
            return session.get(User, state["active"])

    application = create_app()
    application.dependency_overrides[get_db] = session_override
    application.dependency_overrides[current_user] = user_override
    try:
        with TestClient(application) as client:
            yield client, state
    finally:
        application.dependency_overrides.clear()


def _count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_same_request_same_key_creates_only_one_alert_and_outbox(api, pg_engine):
    client, state = api
    url = f"/api/v1/patients/{state['patient']}/safety-alerts"
    header = {"Idempotency-Key": "request-550e8400-e29b-41d4-a716-446655440000"}
    body = {"reason_code": "clinician_review", "priority": "standard"}
    first = client.post(url, json=body, headers=header)
    second = client.post(url, json=body, headers=header)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["delivery_status"] == "not_configured"

    with Session(pg_engine) as session:
        for model in (
            SafetyAlert,
            SafetyAlertEvent,
            SafetyOutbox,
            SafetyOutboxEvent,
            SafetyAlertRequest,
        ):
            assert _count(session, model) == 1
        record = session.scalar(select(SafetyAlertRequest))
        assert record.actor_id == state["first"]
        assert record.patient_id == state["patient"]
        assert len(record.key_digest) == len(record.request_digest) == 64
        assert header["Idempotency-Key"] != record.key_digest

    ack = client.post(f"{url}/{first.json()['id']}/ack")
    assert ack.status_code == 200
    replay = client.post(url, json=body, headers=header)
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["status"] == "acknowledged"


def test_same_key_with_different_request_is_conflict_without_side_effects(api, pg_engine):
    client, state = api
    url = f"/api/v1/patients/{state['patient']}/safety-alerts"
    header = {"Idempotency-Key": "request-conflict-2026"}
    assert client.post(
        url, headers=header, json={"reason_code": "clinician_review", "priority": "standard"}
    ).status_code == 201
    conflict = client.post(
        url, headers=header, json={"reason_code": "clinician_review", "priority": "urgent"}
    )
    assert conflict.status_code == 409
    with Session(pg_engine) as session:
        assert _count(session, SafetyAlert) == 1
        assert _count(session, SafetyOutbox) == 1
        assert _count(session, SafetyAlertRequest) == 1


def test_without_key_retains_old_behavior_and_invalid_key_is_rejected(api, pg_engine):
    client, state = api
    url = f"/api/v1/patients/{state['patient']}/safety-alerts"
    body = {"reason_code": "care_coordination", "priority": "standard"}
    first = client.post(url, json=body)
    second = client.post(url, json=body)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    invalid = client.post(url, json=body, headers={"Idempotency-Key": "short"})
    assert invalid.status_code == 400
    with Session(pg_engine) as session:
        assert _count(session, SafetyAlert) == 2
        assert _count(session, SafetyOutbox) == 2
        assert _count(session, SafetyAlertRequest) == 0


def test_scope_separates_doctors_and_patients_but_preserves_access(api, pg_engine):
    client, state = api
    payload = {"reason_code": "urgent_attention", "priority": "urgent"}
    headers = {"Idempotency-Key": "same-key-new-scope"}
    path = "/api/v1/patients/{}/safety-alerts"
    first = client.post(path.format(state["patient"]), json=payload, headers=headers)
    state["active"] = state["second"]
    second = client.post(path.format(state["patient"]), json=payload, headers=headers)
    state["active"] = state["first"]
    third = client.post(path.format(state["other"]), json=payload, headers=headers)
    assert all(response.status_code == 201 for response in (first, second, third))
    assert len({response.json()["id"] for response in (first, second, third)}) == 3
    state["active"] = state["stranger"]
    response = client.post(path.format(state["patient"]), json=payload, headers=headers)
    assert response.status_code == 404
    state["active"] = state["patient_user"]
    response = client.post(path.format(state["patient"]), json=payload, headers=headers)
    assert response.status_code == 403
    with Session(pg_engine) as session:
        assert _count(session, SafetyAlertRequest) == 3


def test_concurrent_same_key_commits_exactly_once(pg_engine):
    with Session(pg_engine) as session:
        actor = User(username="concurrent-idem", password_hash="x", role="doctor")
        session.add(actor)
        session.flush()
        patient = Patient(alias="SYNTHETIC-RACE", demographics_json={})
        session.add(patient)
        session.commit()
        patient_id, actor_id = patient.id, actor.id

    barrier = Barrier(2)

    def work():
        with Session(pg_engine) as session:
            barrier.wait(timeout=10)
            alert = create_alert(
                session,
                patient_id,
                actor_id,
                SafetyAlertCreate(reason_code="clinician_review", priority="standard"),
                idempotency_key="shared-concurrent-2026",
            )
            return alert.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: work(), range(2)))
    assert len(set(results)) == 1
    with Session(pg_engine) as session:
        for model in (
            SafetyAlert,
            SafetyAlertEvent,
            SafetyOutbox,
            SafetyOutboxEvent,
            SafetyAlertRequest,
        ):
            assert _count(session, model) == 1


def test_concurrent_key_with_two_bodies_rejects_loser(pg_engine):
    with Session(pg_engine) as session:
        actor = User(username="concurrent-different", password_hash="x", role="doctor")
        session.add(actor)
        session.flush()
        patient = Patient(alias="SYNTHETIC-RACE-DIFFERENT", demographics_json={})
        session.add(patient)
        session.commit()
        patient_id, actor_id = patient.id, actor.id

    barrier = Barrier(2)

    def work(priority):
        with Session(pg_engine) as session:
            barrier.wait(timeout=10)
            try:
                alert = create_alert(
                    session,
                    patient_id,
                    actor_id,
                    SafetyAlertCreate(reason_code="clinician_review", priority=priority),
                    idempotency_key="shared-concurrent-conflict-2026",
                )
                return ("ok", alert.id)
            except IdempotencyConflict:
                return ("conflict", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(work, ("standard", "urgent")))
    assert sorted(kind for kind, _ in results) == ["conflict", "ok"]
    with Session(pg_engine) as session:
        for model in (
            SafetyAlert,
            SafetyAlertEvent,
            SafetyOutbox,
            SafetyOutboxEvent,
            SafetyAlertRequest,
        ):
            assert _count(session, model) == 1


def test_failed_outbox_rolls_back_key_and_alert(pg_engine, monkeypatch):
    with Session(pg_engine) as session:
        actor = User(username="failed-idem", password_hash="x", role="doctor")
        session.add(actor)
        session.flush()
        patient = Patient(alias="SYNTHETIC-ROLLBACK", demographics_json={})
        session.add(patient)
        session.commit()
        patient_id, actor_id = patient.id, actor.id

    def broken_enqueue(*args):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr("app.services.safety_alerts.enqueue_alert_created", broken_enqueue)
    with Session(pg_engine) as session:
        with pytest.raises(RuntimeError, match="synthetic failure"):
            create_alert(
                session,
                patient_id,
                actor_id,
                SafetyAlertCreate(reason_code="clinician_review", priority="standard"),
                idempotency_key="rollback-request-2026",
            )
    with Session(pg_engine) as session:
        for model in (SafetyAlert, SafetyAlertEvent, SafetyOutbox, SafetyAlertRequest):
            assert _count(session, model) == 0
