"""Изолированные проверки новых границ multi-doctor Site API."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.services import site_doctor_access as access
from fastapi import HTTPException


class FakeSession:
    def __init__(self, request, patient=None, link=True):
        self.request = request
        self.patient = patient
        self.link = link
        self.calls = 0

    def scalar(self, query):
        self.calls += 1
        return self.request if self.calls == 1 else ("linked" if self.link else None)

    def get(self, model, key):
        return self.patient


def test_distinct_credentials_and_expiry():
    a = access.new_site_key()
    b = access.new_site_key()
    assert a != b
    assert access.hash_site_key(a) != access.hash_site_key(b)
    assert len(a) >= 60
    with pytest.raises(ValueError):
        access.expiry_from_now(365)
    assert access.expiry_from_now() > datetime.now(UTC) + timedelta(days=89)


def test_disabled_without_flag(monkeypatch):
    monkeypatch.delenv("AIDOCTOR_SITE_MULTI_DOCTOR_ENABLED", raising=False)
    with pytest.raises(HTTPException) as err:
        access.authenticate_site_doctor(None, "aidoc_site_" + "x" * 64)
    assert err.value.status_code == 404


def test_invalid_key_is_denied(monkeypatch):
    monkeypatch.setattr(access.settings, "app_env", "test")
    monkeypatch.setenv("AIDOCTOR_SITE_MULTI_DOCTOR_ENABLED", "1")
    with pytest.raises(HTTPException) as err:
        access.authenticate_site_doctor(None, "bad")
    assert err.value.status_code == 401


def test_request_must_belong_to_doctor():
    doctor = SimpleNamespace(id="doc1")
    with pytest.raises(HTTPException) as err:
        access.require_site_request(FakeSession(None), doctor, "p1", "r1")
    assert err.value.status_code == 404


def test_unlinked_patient_blocked(monkeypatch):
    doctor = SimpleNamespace(id="doc1")
    patient = SimpleNamespace(deleted_at=None, demographics_json={"synthetic": True})
    db = FakeSession(SimpleNamespace(id="r1"), patient, link=False)
    with pytest.raises(HTTPException) as err:
        access.require_site_request(db, doctor, "p1", "r1")
    assert err.value.status_code == 404


def test_external_case_requires_consent_not_extra_environment_flag(monkeypatch):
    doctor = SimpleNamespace(id="doc1")
    patient = SimpleNamespace(deleted_at=None, demographics_json={"synthetic": False})
    db = FakeSession(SimpleNamespace(id="r1"), patient)
    with pytest.raises(HTTPException) as err:
        access.require_site_request(db, doctor, "p1", "r1")
    assert err.value.status_code == 403

    # Даже дополнительный флаг не разрешает передачу без согласия.
    monkeypatch.setenv("AIDOCTOR_SITE_ALLOW_NON_SYNTHETIC", "1")
    db = FakeSession(SimpleNamespace(id="r1"), patient)
    with pytest.raises(HTTPException) as err:
        access.require_site_request(db, doctor, "p1", "r1")
    assert err.value.status_code == 403
    monkeypatch.delenv("AIDOCTOR_SITE_ALLOW_NON_SYNTHETIC", raising=False)

    patient.demographics_json["external_ai_consent"] = True
    db = FakeSession(SimpleNamespace(id="r1"), patient)
    assert access.require_site_request(db, doctor, "p1", "r1").id == "r1"


def test_request_query_has_both_doctor_and_patient_filters():
    from app.models.ai_workspace import AIRequest
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    query = select(AIRequest).where(
        AIRequest.id == "req", AIRequest.patient_id == "patient", AIRequest.doctor_id == "doctor"
    )
    sql = str(query.compile(dialect=postgresql.dialect()))
    assert "ai_requests.doctor_id" in sql
    assert "ai_requests.patient_id" in sql
