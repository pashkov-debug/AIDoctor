"""Интеграция 5.6: выполнять с TEST_DATABASE_URL только на локальной *_test БД."""

from datetime import timedelta

import pytest
from app.api.auth import current_user
from app.db.base import utc_now
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from app.models.safety_in_app_notification import SafetyInAppNotification
from app.models.safety_outbox import SafetyOutbox, SafetyOutboxEvent
from app.schemas.safety_alert import SafetyAlertCreate
from app.services.safety_alerts import create_alert
from app.services.safety_in_app_delivery import InAppTransport
from app.services.safety_notification_routes import configure_own_route
from app.services.safety_outbox import claim_due, mark_delivered
from app.workers.safety_outbox import DeliveryEnvelope, TransportFailure, process_one
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def _factory(engine):
    return lambda: Session(engine)


@pytest.fixture
def case(pg_engine):
    with Session(pg_engine) as db:
        doctor = User(username="inapp-doctor", password_hash="x", role="doctor")
        stranger = User(username="inapp-stranger", password_hash="x", role="doctor")
        patient_user = User(username="inapp-patient", password_hash="x", role="patient")
        admin = User(username="inapp-admin", password_hash="x", role="admin")
        db.add_all((doctor, stranger, patient_user, admin))
        db.flush()
        patient = Patient(alias="SYNTHETIC-INAPP", demographics_json={})
        db.add(patient)
        db.flush()
        link = DoctorPatient(doctor_id=doctor.id, patient_id=patient.id)
        db.add(link)
        db.commit()
        alert = create_alert(
            db,
            patient.id,
            doctor.id,
            SafetyAlertCreate(reason_code="clinician_review", priority="standard"),
        )
        outbox = db.scalar(select(SafetyOutbox).where(SafetyOutbox.alert_id == alert.id))
        assert outbox is not None
        return {
            "doctor": doctor.id,
            "stranger": stranger.id,
            "patient_user": patient_user.id,
            "admin": admin.id,
            "patient": patient.id,
            "alert": alert.id,
            "outbox": outbox.id,
            "link": link.id,
            "active": doctor.id,
        }


@pytest.fixture
def client(pg_engine, case):
    def db_override():
        with Session(pg_engine) as db:
            yield db

    def user_override():
        with Session(pg_engine) as db:
            return db.get(User, case["active"])

    application = create_app()
    application.dependency_overrides[get_db] = db_override
    application.dependency_overrides[current_user] = user_override
    try:
        with TestClient(application) as http:
            yield http
    finally:
        application.dependency_overrides.clear()


def _count(engine):
    with Session(engine) as db:
        return db.scalar(select(func.count()).select_from(SafetyInAppNotification))


def _outbox(engine, item_id):
    with Session(engine) as db:
        return db.get(SafetyOutbox, item_id)


def test_explicit_opt_in_creates_one_notification_and_only_own_inbox(pg_engine, case, client):
    factory = _factory(pg_engine)
    assert _count(pg_engine) == 0
    with Session(pg_engine) as db:
        configure_own_route(db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True)

    assert process_one(factory, InAppTransport(factory, enabled=True)) == "delivered"
    assert process_one(factory, InAppTransport(factory, enabled=True)) == "empty"
    assert _count(pg_engine) == 1

    response = client.get("/api/v1/safety-inbox")
    assert response.status_code == 200, response.text
    entries = response.json()
    assert len(entries) == 1
    assert entries[0]["patient_id"] == case["patient"]
    assert entries[0]["alert_id"] == case["alert"]
    assert set(entries[0]) == {"id", "patient_id", "alert_id", "created_at"}

    case["active"] = case["stranger"]
    assert client.get("/api/v1/safety-inbox").json() == []
    case["active"] = case["admin"]
    assert client.get("/api/v1/safety-inbox").status_code == 403
    case["active"] = case["patient_user"]
    assert client.get("/api/v1/safety-inbox").status_code == 403
    with Session(pg_engine) as db:
        events = db.scalars(
            select(SafetyOutboxEvent.event_type).where(
                SafetyOutboxEvent.outbox_id == case["outbox"]
            )
        ).all()
        assert set(events) == {"enqueued", "claimed", "delivered"}


def test_disabled_route_fails_closed_then_retry_can_deliver(pg_engine, case):
    factory = _factory(pg_engine)
    adapter = InAppTransport(factory, enabled=True)
    assert process_one(factory, adapter) == "retry_scheduled"
    assert _count(pg_engine) == 0
    item = _outbox(pg_engine, case["outbox"])
    assert item.status == "pending"
    assert item.last_error_code == "route_unavailable"

    with Session(pg_engine) as db:
        configure_own_route(db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True)
        item = db.get(SafetyOutbox, case["outbox"])
        item.next_attempt_at = utc_now() - timedelta(seconds=1)
        db.commit()

    assert process_one(factory, adapter) == "delivered"
    assert _count(pg_engine) == 1
    assert _outbox(pg_engine, case["outbox"]).attempt_count == 2


def test_inbox_commit_replayed_after_worker_crash_is_idempotent(pg_engine, case):
    factory = _factory(pg_engine)
    with Session(pg_engine) as db:
        configure_own_route(db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True)

    with Session(pg_engine) as db:
        claim = claim_due(db, limit=1)[0]
    adapter = InAppTransport(factory, enabled=True)
    receipt = adapter.send(DeliveryEnvelope.from_claim(claim))
    assert receipt.confirmation_id.startswith("in_app:")
    assert _count(pg_engine) == 1

    # Worker потерял receipt; имитируем истечение lease, новую попытку.
    with Session(pg_engine) as db:
        claim_due(db, now=utc_now() + timedelta(seconds=400))
        item = db.get(SafetyOutbox, case["outbox"])
        item.next_attempt_at = utc_now() - timedelta(seconds=1)
        db.commit()

    with Session(pg_engine) as db:
        new_claim = claim_due(db, limit=1)[0]
    assert new_claim.attempt_number == 2
    assert adapter.send(DeliveryEnvelope.from_claim(new_claim)) == receipt
    assert _count(pg_engine) == 1
    with Session(pg_engine) as db:
        mark_delivered(db, new_claim)
    assert _outbox(pg_engine, case["outbox"]).status == "delivered"


def test_stale_or_unclaimed_envelope_fails_without_writing(pg_engine, case):
    adapter = InAppTransport(_factory(pg_engine), enabled=True)
    with Session(pg_engine) as db:
        configure_own_route(db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True)
    envelope = DeliveryEnvelope(
        outbox_id=case["outbox"],
        alert_id=case["alert"],
        event_type="created",
        attempt_number=1,
    )
    with pytest.raises(TransportFailure):
        adapter.send(envelope)
    assert _count(pg_engine) == 0


def test_revoked_link_and_deleted_patient_hide_existing_inbox(pg_engine, case, client):
    factory = _factory(pg_engine)
    with Session(pg_engine) as db:
        configure_own_route(db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True)
    assert process_one(factory, InAppTransport(factory, enabled=True)) == "delivered"
    assert len(client.get("/api/v1/safety-inbox").json()) == 1
    with Session(pg_engine) as db:
        db.query(DoctorPatient).filter_by(id=case["link"]).delete()
        db.commit()
    assert client.get("/api/v1/safety-inbox").json() == []
    with Session(pg_engine) as db:
        db.add(DoctorPatient(doctor_id=case["doctor"], patient_id=case["patient"]))
        patient = db.get(Patient, case["patient"])
        patient.deleted_at = utc_now()
        db.commit()
    assert client.get("/api/v1/safety-inbox").json() == []
