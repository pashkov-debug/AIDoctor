"""PostgreSQL-интеграция worker: только синтетический транспорт."""

from datetime import timedelta

import pytest
from app.db.base import utc_now
from app.db.metadata import metadata
from app.models.access import User
from app.models.patient import Patient
from app.models.safety_outbox import SafetyOutbox, SafetyOutboxEvent
from app.schemas.safety_alert import SafetyAlertCreate
from app.services.safety_alerts import create_alert
from app.services.safety_outbox import claim_due
from app.workers.safety_outbox import (
    DeliveryReceipt,
    TransportFailure,
    TransportNotConfigured,
    get_status_counts,
    process_one,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


def _seed(engine):
    assert "safety_outbox" in metadata.tables
    with Session(engine) as session:
        doctor = User(username="synthetic-worker-doctor", password_hash="x", role="doctor")
        session.add(doctor)
        session.flush()
        patient = Patient(alias="SYNTHETIC-WORKER", demographics_json={})
        session.add(patient)
        session.flush()
        alert = create_alert(
            session,
            patient.id,
            doctor.id,
            SafetyAlertCreate(reason_code="clinician_review", priority="standard"),
        )
        return alert.id

def _factory(engine):
    return lambda: Session(engine)

def _entry(engine, alert_id):
    with Session(engine) as session:
        item = session.scalar(
            select(SafetyOutbox).where(SafetyOutbox.alert_id == alert_id)
        )
        assert item is not None
        return item.id, item.status, item.attempt_count

def _events(engine, outbox_id):
    with Session(engine) as session:
        return list(session.scalars(
            select(SafetyOutboxEvent.event_type)
            .where(SafetyOutboxEvent.outbox_id == outbox_id)
            .order_by(SafetyOutboxEvent.created_at, SafetyOutboxEvent.id)
        ).all())


class SyntheticReceiptTransport:
    def __init__(self):
        self.calls = 0

    def send(self, envelope):
        self.calls += 1
        assert envelope.event_type == "created"
        return DeliveryReceipt("synthetic:confirmation:1234")


class SyntheticFailureTransport:
    def send(self, envelope):
        raise TransportFailure("provider_unavailable")


def test_no_transport_leaves_outbox_untouched(pg_engine):
    alert_id = _seed(pg_engine)
    factory = _factory(pg_engine)
    before = _entry(pg_engine, alert_id)
    with pytest.raises(TransportNotConfigured):
        process_one(factory, None)
    assert _entry(pg_engine, alert_id) == before
    with Session(pg_engine) as session:
        assert get_status_counts(session)["pending"] == 1
    assert _events(pg_engine, before[0]) == ["enqueued"]


def test_successful_synthetic_receipt_and_audit(pg_engine):
    alert_id = _seed(pg_engine)
    transport = SyntheticReceiptTransport()
    factory = _factory(pg_engine)
    assert process_one(factory, transport) == "delivered"
    assert process_one(factory, transport) == "empty"
    assert transport.calls == 1
    item_id, status, attempts = _entry(pg_engine, alert_id)
    assert (status, attempts) == ("delivered", 1)
    assert _events(pg_engine, item_id) == ["enqueued", "claimed", "delivered"]


def test_failure_records_only_category(pg_engine):
    alert_id = _seed(pg_engine)
    assert process_one(_factory(pg_engine), SyntheticFailureTransport()) == "retry_scheduled"
    outbox_id, status, attempts = _entry(pg_engine, alert_id)
    assert (status, attempts) == ("pending", 1)
    assert _events(pg_engine, outbox_id) == [
        "enqueued", "claimed", "retry_scheduled"
    ]
    with Session(pg_engine) as session:
        item = session.get(SafetyOutbox, outbox_id)
        assert item.last_error_code == "provider_unavailable"
        assert item.next_attempt_at > utc_now()


def test_expired_lease_rejects_late_positive_receipt(pg_engine):
    alert_id = _seed(pg_engine)

    class LateTransport:
        def send(self, envelope):
            with Session(pg_engine) as session:
                # Только имитация истечения lease: время реального провайдера не меняем.
                claim_due(session, now=utc_now() + timedelta(seconds=400))
            return DeliveryReceipt("synthetic:late:12345")

    assert process_one(_factory(pg_engine), LateTransport()) == "stale"
    outbox_id, status, attempts = _entry(pg_engine, alert_id)
    assert (status, attempts) == ("pending", 1)
    assert _events(pg_engine, outbox_id) == [
        "enqueued", "claimed", "retry_scheduled"
    ]
