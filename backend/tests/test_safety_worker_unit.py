"""Контракт worker: только имитация транспорта, без PostgreSQL и отправки."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from app.services.safety_outbox import InvalidOutboxClaim, OutboxClaim
from app.workers import safety_outbox as worker

CLAIM = OutboxClaim(
    outbox_id="outbox-id",
    alert_id="alert-id",
    event_type="created",
    token="lease-token",
    attempt_number=1,
)


class SessionFactory:
    def __init__(self):
        self.opened = 0
        self.active = 0

    @contextmanager
    def __call__(self):
        self.opened += 1
        self.active += 1
        try:
            yield object()
        finally:
            self.active -= 1


class FakeTransport:
    def __init__(self, factory, response):
        self.factory = factory
        self.response = response
        self.called = 0

    def send(self, envelope):
        assert self.factory.active == 0  # во время отправки нет DB Session
        assert envelope == worker.DeliveryEnvelope(
            "outbox-id", "alert-id", "created", 1
        )
        assert not hasattr(envelope, "patient_id")
        self.called += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_absent_transport_does_not_claim(monkeypatch):
    factory = SessionFactory()

    def forbidden(*args, **kwargs):
        raise AssertionError("Нельзя резервировать без транспорта")

    monkeypatch.setattr(worker, "claim_due", forbidden)
    with pytest.raises(worker.TransportNotConfigured):
        worker.process_one(factory, None)
    assert factory.opened == 0
    with pytest.raises(ValueError, match="lease_seconds"):
        worker.process_one(factory, FakeTransport(factory, None), lease_seconds=20)
    assert factory.opened == 0


def test_success_uses_separate_sessions_and_confirms(monkeypatch):
    factory = SessionFactory()
    transport = FakeTransport(factory, worker.DeliveryReceipt("receipt:1234"))
    monkeypatch.setattr(worker, "claim_due", lambda *a, **kw: [CLAIM])
    completed = []

    def confirm(session, claim):
        completed.append(claim)
        assert factory.active == 1

    monkeypatch.setattr(worker, "mark_delivered", confirm)
    monkeypatch.setattr(
        worker, "mark_attempt_failed",
        lambda *a, **kw: pytest.fail("Не должно быть ошибки доставки"),
    )
    assert worker.process_one(factory, transport) == "delivered"
    assert transport.called == 1
    assert completed == [CLAIM]
    assert factory.opened == 2
    assert factory.active == 0


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (worker.TransportFailure("provider_timeout"), "provider_timeout"),
        (worker.DeliveryReceipt(""), "unconfirmed_delivery"),
        (None, "unconfirmed_delivery"),
        (SimpleNamespace(confirmation_id="receipt:1234"), "unconfirmed_delivery"),
        (RuntimeError("secret patient note"), "transport_unexpected"),
    ],
)
def test_errors_are_sanitized_and_never_mark_delivered(
    monkeypatch, response, expected_code
):
    factory = SessionFactory()
    transport = FakeTransport(factory, response)
    monkeypatch.setattr(worker, "claim_due", lambda *a, **kw: [CLAIM])
    called = []
    monkeypatch.setattr(
        worker, "mark_attempt_failed",
        lambda session, claim, *, error_code: called.append(error_code),
    )
    monkeypatch.setattr(
        worker, "mark_delivered",
        lambda *a, **kw: pytest.fail("Нет подтверждения"),
    )
    assert worker.process_one(factory, transport) == "retry_scheduled"
    assert called == [expected_code]


def test_third_failure_is_terminal(monkeypatch):
    factory = SessionFactory()
    claim = OutboxClaim("outbox", "alert", "created", "token", 3)
    monkeypatch.setattr(worker, "claim_due", lambda *a, **kw: [claim])
    monkeypatch.setattr(worker, "mark_attempt_failed", lambda *a, **kw: None)
    assert worker.process_one(
        factory, FakeTransport(factory, worker.TransportFailure("provider_rejected"))
    ) == "failed"


def test_empty_does_not_invoke_transport(monkeypatch):
    factory = SessionFactory()
    transport = FakeTransport(factory, None)
    monkeypatch.setattr(worker, "claim_due", lambda *a, **kw: [])
    assert worker.process_one(factory, transport) == "empty"
    assert transport.called == 0
    assert factory.opened == 1


def test_old_lease_is_not_confirmed(monkeypatch):
    factory = SessionFactory()
    monkeypatch.setattr(worker, "claim_due", lambda *a, **kw: [CLAIM])

    def stale(session, claim):
        raise InvalidOutboxClaim()

    monkeypatch.setattr(worker, "mark_delivered", stale)
    assert worker.process_one(
        factory, FakeTransport(factory, worker.DeliveryReceipt("receipt-98765"))
    ) == "stale"


def test_transport_error_code_allowlist():
    with pytest.raises(ValueError, match="категория"):
        worker.TransportFailure("diagnosis_secret")
    with pytest.raises(ValueError, match="категория"):
        worker.TransportFailure("")


def test_cli_requires_status_and_does_not_open_session():
    assert worker.main([]) == 2


def test_status_reads_only_aggregates():
    class FakeSession:
        def execute(self, query):
            return [("pending", 7), ("failed", 2)]

    assert worker.get_status_counts(FakeSession()) == {
        "pending": 7,
        "processing": 0,
        "delivered": 0,
        "failed": 2,
    }
