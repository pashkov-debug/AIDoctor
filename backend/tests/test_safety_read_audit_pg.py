"""PostgreSQL API: successful reads, no leakage, fail-closed audit."""

import pytest
from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from app.models.safety_read_audit import SafetyReadAudit
from app.schemas.safety_alert import SafetyAlertCreate
from app.services.safety_alerts import create_alert
from app.services.safety_notification_routes import configure_own_route
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.fixture
def case(pg_engine):
    with Session(pg_engine) as session:
        doctor = User(username="audit-doctor", role="doctor", password_hash="x")
        other = User(username="audit-other", role="doctor", password_hash="x")
        admin = User(username="audit-admin", role="admin", password_hash="x")
        session.add_all((doctor, other, admin))
        session.flush()
        patient = Patient(alias="SYNTHETIC-AUDIT", demographics_json={})
        session.add(patient)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        session.commit()
        create_alert(
            session,
            patient.id,
            doctor.id,
            SafetyAlertCreate(reason_code="clinician_review", priority="standard"),
        )
        configure_own_route(session, patient_id=patient.id, actor_id=doctor.id, enabled=True)
        return {
            "doctor": doctor.id,
            "other": other.id,
            "admin": admin.id,
            "patient": patient.id,
            "active": doctor.id,
        }


@pytest.fixture
def client(pg_engine, case):
    def db_override():
        with Session(pg_engine) as session:
            yield session

    def user_override():
        with Session(pg_engine) as session:
            return session.get(User, case["active"])

    app = create_app()
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[current_user] = user_override
    try:
        with TestClient(app, raise_server_exceptions=False) as http:
            yield http
    finally:
        app.dependency_overrides.clear()


def _audits(engine):
    with Session(engine) as session:
        return list(
            session.scalars(select(SafetyReadAudit).order_by(SafetyReadAudit.created_at)).all()
        )


def test_successful_gets_audit_even_empty_results(pg_engine, case, client):
    prefix = "/api/v1"
    patient_id = case["patient"]
    urls = [
        f"{prefix}/patients/{patient_id}/safety-alerts",
        f"{prefix}/patients/{patient_id}/safety-notification-route",
        f"{prefix}/safety-inbox",
        f"{prefix}/safety-followups",
    ]
    expected = [1, 1, 0, 0]
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, (url, response.text)
    rows = _audits(pg_engine)
    assert len(rows) == 4
    assert {item.scope: item.returned_count for item in rows} == dict(
        zip(
            ("alerts_list", "route_read", "inbox_list", "followups_list"),
            expected,
            strict=True,
        )
    )
    assert all(item.actor_id == case["doctor"] for item in rows)
    assert {item.patient_id for item in rows if item.patient_id} == {patient_id}
    assert all(
        item.patient_id is None for item in rows if item.scope in ("inbox_list", "followups_list")
    )


def test_denied_reads_do_not_write_success_audit(pg_engine, case, client):
    patient_id = case["patient"]
    case["active"] = case["other"]
    assert client.get(f"/api/v1/patients/{patient_id}/safety-alerts").status_code == 404
    assert client.get(f"/api/v1/patients/{patient_id}/safety-notification-route").status_code == 404
    assert client.get("/api/v1/safety-inbox").status_code == 200
    assert client.get("/api/v1/safety-followups").status_code == 200
    case["active"] = case["admin"]
    assert client.get("/api/v1/safety-inbox").status_code == 403
    assert client.get("/api/v1/safety-followups").status_code == 403
    assert client.get(f"/api/v1/patients/{patient_id}/safety-notification-route").status_code == 403
    rows = _audits(pg_engine)
    assert len(rows) == 2
    assert {item.scope for item in rows} == {"inbox_list", "followups_list"}
    assert all(item.actor_id == case["other"] for item in rows)


def test_audit_write_failure_blocks_http_response(pg_engine, case, client, monkeypatch):
    from app.api.routes import safety_in_app_notifications

    def failing_read(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(safety_in_app_notifications, "record_safety_read", failing_read)
    response = client.get("/api/v1/safety-inbox")
    assert response.status_code == 500
    assert _audits(pg_engine) == []


def test_no_patient_medical_data_in_audit_rows(pg_engine, case, client):
    response = client.get(f"/api/v1/patients/{case['patient']}/safety-alerts")
    assert response.status_code == 200
    row = _audits(pg_engine)[0]
    assert set(row.__table__.columns.keys()) == {
        "id",
        "created_at",
        "actor_id",
        "patient_id",
        "scope",
        "returned_count",
    }
    assert "SYNTHETIC-AUDIT" not in repr(row.__dict__)
