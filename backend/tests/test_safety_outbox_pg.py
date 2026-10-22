"""PostgreSQL-тесты Outbox: только TEST_DATABASE_URL, никаких внешних отправок."""

from datetime import timedelta

import pytest
from app.api.auth import current_user
from app.db.base import utc_now
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from app.models.safety_alert import SafetyAlert, SafetyAlertEvent
from app.models.safety_outbox import SafetyOutbox, SafetyOutboxEvent
from app.schemas.safety_alert import SafetyAlertCreate
from app.services.safety_alerts import create_alert
from app.services.safety_outbox import (
    InvalidOutboxClaim,
    claim_due,
    enqueue_alert_created,
    mark_attempt_failed,
    mark_delivered,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def _create_people(engine):
    with Session(engine) as session:
        doctor = User(username="outbox-doctor", password_hash="x", role="doctor")
        session.add(doctor)
        session.flush()
        patient = Patient(alias="SYNTHETIC-OUTBOX", demographics_json={})
        session.add(patient)
        session.commit()
        return doctor.id, patient.id


def _create_alert(engine):
    doctor_id, patient_id = _create_people(engine)
    with Session(engine) as session:
        alert = create_alert(
            session,
            patient_id,
            doctor_id,
            SafetyAlertCreate(reason_code="clinician_review", priority="standard"),
        )
        return alert.id


def _events(session, outbox_id):
    return list(
        session.scalars(
            select(SafetyOutboxEvent)
            .where(SafetyOutboxEvent.outbox_id == outbox_id)
            .order_by(SafetyOutboxEvent.created_at, SafetyOutboxEvent.id)
        ).all()
    )


def test_create_outbox_is_atomic_and_enqueue_is_idempotent(pg_engine):
    alert_id = _create_alert(pg_engine)
    with Session(pg_engine) as session:
        entry = session.scalar(select(SafetyOutbox).where(SafetyOutbox.alert_id == alert_id))
        assert entry is not None
        assert entry.status == "pending"
        assert entry.attempt_count == 0
        assert entry.event_type == "created"
        assert enqueue_alert_created(session, alert_id) == entry.id
        assert enqueue_alert_created(session, alert_id) == entry.id
        session.commit()
        assert session.scalar(select(func.count()).select_from(SafetyOutbox)) == 1
        assert [e.event_type for e in _events(session, entry.id)] == ["enqueued"]


def test_api_creation_keeps_existing_delivery_status(pg_engine):
    doctor_id, patient_id = _create_people(pg_engine)

    def override_db():
        with Session(pg_engine) as session:
            yield session

    def override_user():
        with Session(pg_engine) as session:
            return session.get(User, doctor_id)

    # Явная связь врач-пациент, как требует действующая авторизация.
    with Session(pg_engine) as session:
        session.add(DoctorPatient(doctor_id=doctor_id, patient_id=patient_id))
        session.commit()

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[current_user] = override_user
    try:
        with TestClient(app) as client:
            result = client.post(
                f"/api/v1/patients/{patient_id}/safety-alerts",
                json={"reason_code": "urgent_attention", "priority": "urgent"},
            )
            assert result.status_code == 201, result.text
            assert result.json()["delivery_status"] == "not_configured"
            alert_id = result.json()["id"]
    finally:
        app.dependency_overrides.clear()

    with Session(pg_engine) as session:
        record = session.scalar(select(SafetyOutbox).where(SafetyOutbox.alert_id == alert_id))
        assert record is not None and record.status == "pending"


def test_retries_exhaustion_audit_and_old_token(pg_engine):
    alert_id = _create_alert(pg_engine)
    start = utc_now() + timedelta(seconds=1)
    with Session(pg_engine) as session:
        first = claim_due(session, now=start, lease_seconds=60)
        assert len(first) == 1
        assert first[0].alert_id == alert_id
        assert claim_due(session, now=start + timedelta(seconds=1)) == []
        mark_attempt_failed(
            session,
            first[0],
            error_code="provider_unavailable",
            now=start + timedelta(seconds=2),
        )
        assert claim_due(session, now=start + timedelta(seconds=30)) == []
        second = claim_due(session, now=start + timedelta(seconds=33))
        assert len(second) == 1 and second[0].attempt_number == 2
        assert second[0].token != first[0].token

        with pytest.raises(InvalidOutboxClaim):
            mark_delivered(session, first[0], now=start + timedelta(seconds=34))

        mark_attempt_failed(
            session,
            second[0],
            error_code="provider_unavailable",
            now=start + timedelta(seconds=34),
        )
        assert claim_due(session, now=start + timedelta(seconds=93)) == []
        third = claim_due(session, now=start + timedelta(seconds=95))
        assert len(third) == 1 and third[0].attempt_number == 3
        mark_attempt_failed(
            session,
            third[0],
            error_code="provider_unavailable",
            now=start + timedelta(seconds=96),
        )
        assert claim_due(session, now=start + timedelta(days=1)) == []
        entry = session.get(SafetyOutbox, first[0].outbox_id)
        session.refresh(entry)
        assert entry.status == "failed"
        assert entry.attempt_count == 3
        assert entry.last_error_code == "provider_unavailable"
        assert [e.event_type for e in _events(session, entry.id)] == [
            "enqueued",
            "claimed",
            "retry_scheduled",
            "claimed",
            "retry_scheduled",
            "claimed",
            "exhausted",
        ]


def test_expired_lease_recovered_and_success_recorded_only_explicitly(pg_engine):
    _create_alert(pg_engine)
    start = utc_now() + timedelta(seconds=1)
    with Session(pg_engine) as session:
        first = claim_due(session, now=start, lease_seconds=30)[0]
        # Нет worker: истёкшее резервирование переводится в pending с backoff.
        assert claim_due(session, now=start + timedelta(seconds=31)) == []
        with pytest.raises(InvalidOutboxClaim):
            mark_delivered(session, first, now=start + timedelta(seconds=32))
        next_claim = claim_due(session, now=start + timedelta(seconds=62))[0]
        assert next_claim.attempt_number == 2
        mark_delivered(session, next_claim, now=start + timedelta(seconds=63))
        entry = session.get(SafetyOutbox, first.outbox_id)
        session.refresh(entry)
        assert entry.status == "delivered"
        assert entry.delivered_at is not None
        assert entry.claim_token is None
        assert [e.event_type for e in _events(session, entry.id)] == [
            "enqueued",
            "claimed",
            "retry_scheduled",
            "claimed",
            "delivered",
        ]


def test_create_transaction_rolls_back_everything(pg_engine, monkeypatch):
    doctor_id, patient_id = _create_people(pg_engine)

    def fail_enqueue(*args):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr("app.services.safety_alerts.enqueue_alert_created", fail_enqueue)
    with Session(pg_engine) as session:
        with pytest.raises(RuntimeError, match="synthetic failure"):
            create_alert(
                session,
                patient_id,
                doctor_id,
                SafetyAlertCreate(reason_code="clinician_review", priority="standard"),
            )
    with Session(pg_engine) as session:
        for model in (SafetyAlert, SafetyAlertEvent, SafetyOutbox, SafetyOutboxEvent):
            assert session.scalar(select(func.count()).select_from(model)) == 0
