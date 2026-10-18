"""PostgreSQL-тесты 5.5: только синтетические данные и локальная *_test БД."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from app.models.safety_notification_route import (
    SafetyNotificationRoute,
    SafetyNotificationRouteEvent,
)
from app.services.safety_notification_routes import (
    RouteAccessDenied,
    configure_own_route,
    eligible_routes,
)
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


@pytest.fixture
def case(pg_engine):
    with Session(pg_engine) as db:
        doctor = User(username="route-doctor", password_hash="x", role="doctor")
        stranger = User(username="route-stranger", password_hash="x", role="doctor")
        admin = User(username="route-admin", password_hash="x", role="admin")
        patient_user = User(username="route-patient", password_hash="x", role="patient")
        db.add_all((doctor, stranger, admin, patient_user))
        db.flush()
        patient = Patient(alias="SYNTHETIC-ROUTE", user_id=patient_user.id, demographics_json={})
        other = Patient(alias="SYNTHETIC-OTHER", demographics_json={})
        db.add_all((patient, other))
        db.flush()
        link = DoctorPatient(doctor_id=doctor.id, patient_id=patient.id)
        db.add(link)
        db.commit()
        return {
            "doctor": doctor.id, "stranger": stranger.id, "admin": admin.id,
            "patient_user": patient_user.id, "patient": patient.id,
            "other": other.id, "link": link.id, "active": doctor.id,
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


def _url(case):
    return f"/api/v1/patients/{case['patient']}/safety-notification-route"


def _count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_opt_in_self_only_idempotent_and_audited(client, case, pg_engine):
    url = _url(case)
    assert client.get(url).json() is None
    enabled = client.put(url, json={"enabled": True, "channel": "in_app"})
    assert enabled.status_code == 200, enabled.text
    payload = enabled.json()
    assert payload["recipient_user_id"] == case["doctor"]
    assert payload["confirmed_at"] is not None
    assert client.put(url, json={"enabled": True}).json()["id"] == payload["id"]
    assert client.get(url).json()["enabled"] is True

    with Session(pg_engine) as db:
        assert _count(db, SafetyNotificationRoute) == 1
        assert _count(db, SafetyNotificationRouteEvent) == 1
        recipients = eligible_routes(db, patient_id=case["patient"])
        assert len(recipients) == 1
        assert recipients[0].recipient_user_id == case["doctor"]
        assert recipients[0].channel == "in_app"
        assert eligible_routes(db, patient_id=case["other"]) == ()

    disabled = client.put(url, json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert client.put(url, json={"enabled": False}).status_code == 200
    with Session(pg_engine) as db:
        assert _count(db, SafetyNotificationRouteEvent) == 2
        assert eligible_routes(db, patient_id=case["patient"]) == ()


def test_rbac_and_channels_fail_closed(client, case, pg_engine):
    url = _url(case)
    assert client.put(url, json={"enabled": True, "channel": "sms"}).status_code == 422
    assert client.put(url, json={"enabled": True, "other": "secret"}).status_code == 422
    assert client.put(url, json={"enabled": "garbage"}).status_code == 422
    case["active"] = case["stranger"]
    assert client.get(url).status_code == 404
    assert client.put(url, json={"enabled": True}).status_code == 404
    case["active"] = case["patient_user"]
    assert client.get(url).status_code == 403
    assert client.put(url, json={"enabled": True}).status_code == 403
    case["active"] = case["admin"]
    assert client.put(url, json={"enabled": True}).status_code == 403
    with Session(pg_engine) as db:
        assert _count(db, SafetyNotificationRoute) == 0
        assert _count(db, SafetyNotificationRouteEvent) == 0
        assert eligible_routes(db, patient_id=case["patient"]) == ()


def test_deleted_patient_and_revoked_access_disable_resolution(pg_engine, case):
    with Session(pg_engine) as db:
        configure_own_route(
            db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True
        )
    with Session(pg_engine) as db:
        db.query(DoctorPatient).filter_by(id=case["link"]).delete()
        db.commit()
        assert eligible_routes(db, patient_id=case["patient"]) == ()
        with pytest.raises(RouteAccessDenied):
            configure_own_route(
                db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True
            )
    with Session(pg_engine) as db:
        db.add(DoctorPatient(doctor_id=case["doctor"], patient_id=case["patient"]))
        patient = db.get(Patient, case["patient"])
        from app.db.base import utc_now
        patient.deleted_at = utc_now()
        db.commit()
        assert eligible_routes(db, patient_id=case["patient"]) == ()


def test_unconfirmed_or_wrong_role_cannot_be_eligible(pg_engine, case):
    with Session(pg_engine) as db:
        db.add(
            SafetyNotificationRoute(
                patient_id=case["patient"],
                recipient_user_id=case["doctor"],
                channel="in_app", enabled=False, confirmed_at=None,
            )
        )
        db.commit()
        assert eligible_routes(db, patient_id=case["patient"]) == ()
        route = db.scalar(select(SafetyNotificationRoute))
        from app.db.base import utc_now
        route.confirmed_at = utc_now()
        route.enabled = True
        db.commit()
        assert len(eligible_routes(db, patient_id=case["patient"])) == 1
        db.get(User, case["doctor"]).role = "patient"
        db.commit()
        assert eligible_routes(db, patient_id=case["patient"]) == ()


def test_simultaneous_enable_is_single_record_and_event(pg_engine, case):
    barrier = Barrier(2)

    def enable():
        with Session(pg_engine) as db:
            barrier.wait(timeout=10)
            return configure_own_route(
                db, patient_id=case["patient"], actor_id=case["doctor"], enabled=True
            ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(lambda _: enable(), range(2)))
    assert ids[0] == ids[1]
    with Session(pg_engine) as db:
        assert _count(db, SafetyNotificationRoute) == 1
        assert _count(db, SafetyNotificationRouteEvent) == 1
