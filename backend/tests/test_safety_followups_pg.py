"""PostgreSQL-only интеграция административных follow-up 5.7."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from app.api.auth import current_user
from app.db.base import utc_now
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from app.models.safety_alert import SafetyAlert
from app.models.safety_followup import SafetyFollowup
from app.schemas.safety_alert import SafetyAlertCreate
from app.services.safety_alerts import acknowledge_alert, create_alert
from app.services.safety_followups import (
    MAX_FOLLOWUPS_PER_DOCTOR_WINDOW,
    create_one_due_followup,
    list_own_open_followups,
)
from app.services.safety_notification_routes import configure_own_route
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


@pytest.fixture
def case(pg_engine):
    with Session(pg_engine) as db:
        doctor = User(username="followup-doctor", role="doctor", password_hash="x")
        second = User(username="followup-second", role="doctor", password_hash="x")
        admin = User(username="followup-admin", role="admin", password_hash="x")
        db.add_all((doctor, second, admin))
        db.flush()
        patient = Patient(alias="SYNTHETIC-FOLLOWUP", demographics_json={})
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
        return {
            "doctor": doctor.id,
            "second": second.id,
            "admin": admin.id,
            "patient": patient.id,
            "link": link.id,
            "alert": alert.id,
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

    app = create_app()
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[current_user] = user_override
    try:
        with TestClient(app) as http:
            yield http
    finally:
        app.dependency_overrides.clear()


def _overdue(engine, alert_id, *, hours=26):
    with Session(engine) as db:
        alert = db.get(SafetyAlert, alert_id)
        alert.created_at = utc_now() - timedelta(hours=hours)
        db.commit()


def _count(engine):
    with Session(engine) as db:
        return db.scalar(select(func.count(SafetyFollowup.id)))


def test_no_route_and_not_due_cannot_create(pg_engine, case):
    _overdue(pg_engine, case["alert"])
    with Session(pg_engine) as db:
        assert create_one_due_followup(db) == "empty"
    assert _count(pg_engine) == 0

    with Session(pg_engine) as db:
        configure_own_route(
            db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True
        )
    with Session(pg_engine) as db:
        db.get(SafetyAlert, case["alert"]).created_at = utc_now()
        db.commit()
    with Session(pg_engine) as db:
        assert create_one_due_followup(db) == "empty"
    assert _count(pg_engine) == 0


def test_once_dedup_api_access_and_ack_hides(pg_engine, case, client):
    _overdue(pg_engine, case["alert"])
    with Session(pg_engine) as db:
        configure_own_route(
            db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True
        )
    with Session(pg_engine) as db:
        assert create_one_due_followup(db) == "created"
    with Session(pg_engine) as db:
        assert create_one_due_followup(db) == "empty"
    assert _count(pg_engine) == 1

    response = client.get("/api/v1/safety-followups")
    assert response.status_code == 200, response.text
    assert len(response.json()) == 1
    assert set(response.json()[0]) == {"id", "patient_id", "alert_id", "created_at"}

    case["active"] = case["second"]
    assert client.get("/api/v1/safety-followups").json() == []
    case["active"] = case["admin"]
    assert client.get("/api/v1/safety-followups").status_code == 403

    with Session(pg_engine) as db:
        acknowledge_alert(db, case["patient"], case["alert"], case["doctor"])
    case["active"] = case["doctor"]
    assert client.get("/api/v1/safety-followups").json() == []
    assert _count(pg_engine) == 1  # Не удаляем след аудита.


def test_route_disable_link_revoke_and_soft_delete_hide(pg_engine, case):
    _overdue(pg_engine, case["alert"])
    with Session(pg_engine) as db:
        configure_own_route(
            db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True
        )
        assert create_one_due_followup(db) == "created"

    with Session(pg_engine) as db:
        assert len(list_own_open_followups(db, recipient_user_id=case["doctor"])) == 1
        configure_own_route(
            db, patient_id=case["patient"], actor_id=case["doctor"], enabled=False
        )
        assert list_own_open_followups(db, recipient_user_id=case["doctor"]) == []
        configure_own_route(
            db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True
        )
        assert len(list_own_open_followups(db, recipient_user_id=case["doctor"])) == 1
        db.query(DoctorPatient).filter_by(id=case["link"]).delete()
        db.commit()

    with Session(pg_engine) as db:
        assert list_own_open_followups(db, recipient_user_id=case["doctor"]) == []
        db.add(DoctorPatient(doctor_id=case["doctor"], patient_id=case["patient"]))
        db.get(Patient, case["patient"]).deleted_at = utc_now()
        db.commit()
    with Session(pg_engine) as db:
        assert list_own_open_followups(db, recipient_user_id=case["doctor"]) == []
    assert _count(pg_engine) == 1


def test_bounded_rate_per_doctor_window(pg_engine, case):
    with Session(pg_engine) as db:
        configure_own_route(
            db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True
        )
    _overdue(pg_engine, case["alert"])
    for i in range(MAX_FOLLOWUPS_PER_DOCTOR_WINDOW):
        if i:
            with Session(pg_engine) as db:
                alert = create_alert(
                    db,
                    case["patient"],
                    case["doctor"],
                    SafetyAlertCreate(reason_code="care_coordination", priority="standard"),
                )
            _overdue(pg_engine, alert.id)
        with Session(pg_engine) as db:
            assert create_one_due_followup(db) == "created"

    with Session(pg_engine) as db:
        sixth = create_alert(
            db,
            case["patient"],
            case["doctor"],
            SafetyAlertCreate(reason_code="clinician_review", priority="urgent"),
        )
    _overdue(pg_engine, sixth.id)
    with Session(pg_engine) as db:
        assert create_one_due_followup(db) == "empty"
    assert _count(pg_engine) == MAX_FOLLOWUPS_PER_DOCTOR_WINDOW


def test_concurrent_runs_create_one(pg_engine, case):
    _overdue(pg_engine, case["alert"])
    with Session(pg_engine) as db:
        configure_own_route(
            db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True
        )

    def run():
        with Session(pg_engine) as db:
            return create_one_due_followup(db)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: run(), range(2)))
    assert outcomes.count("created") == 1
    assert _count(pg_engine) == 1
