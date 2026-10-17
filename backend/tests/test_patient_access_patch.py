"""Проверка запрета доступа к карточкам пациентов через HTTP API."""

from collections.abc import Iterator

import pytest
from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def access_client(pg_engine) -> Iterator[tuple[TestClient, dict]]:
    with Session(pg_engine) as session:
        admin = User(username="patch-admin", password_hash="x", role="admin")
        doctor_a = User(username="patch-dr-a", password_hash="x", role="doctor")
        doctor_b = User(username="patch-dr-b", password_hash="x", role="doctor")
        patient_user = User(username="patch-pat", password_hash="x", role="patient")
        session.add_all([admin, doctor_a, doctor_b, patient_user])
        session.flush()

        owned = Patient(alias="OWNED", demographics_json={"synthetic": True},
                        user_id=patient_user.id)
        other = Patient(alias="OTHER", demographics_json={"synthetic": True})
        session.add_all([owned, other])
        session.flush()
        session.add_all([
            DoctorPatient(doctor_id=doctor_a.id, patient_id=owned.id),
            DoctorPatient(doctor_id=doctor_b.id, patient_id=other.id),
        ])
        state = {
            "admin": admin.id,
            "doctor_a": doctor_a.id,
            "doctor_b": doctor_b.id,
            "patient": patient_user.id,
            "owned": owned.id,
            "other": other.id,
            "active_user": doctor_a.id,
        }
        session.commit()

    def db_override():
        with Session(pg_engine) as db:
            yield db

    def user_override():
        with Session(pg_engine) as db:
            return db.get(User, state["active_user"])

    app = create_app()
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[current_user] = user_override
    try:
        with TestClient(app) as client:
            yield client, state
    finally:
        app.dependency_overrides.clear()


def test_doctor_only_sees_assigned_patient(access_client):
    client, state = access_client
    response = client.get("/api/v1/patients")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [state["owned"]]
    assert client.get(f"/api/v1/patients/{state['owned']}").status_code == 200
    assert client.get(f"/api/v1/patients/{state['other']}").status_code == 404
    assert client.get("/api/v1/patients?search=OTHER").json()["total"] == 0


def test_patient_only_sees_own_card_and_cannot_create(access_client):
    client, state = access_client
    state["active_user"] = state["patient"]
    response = client.get("/api/v1/patients")
    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [state["owned"]]
    assert client.get(f"/api/v1/patients/{state['other']}").status_code == 404
    assert client.post("/api/v1/patients", json={"alias": "BAD"}).status_code == 403


def test_new_patient_linked_to_creating_doctor(access_client):
    client, state = access_client
    created = client.post(
        "/api/v1/patients",
        json={"alias": "NEW-SYNTHETIC", "demographics": {}},
    )
    assert created.status_code == 201, created.text
    patient_id = created.json()["id"]
    assert client.get(f"/api/v1/patients/{patient_id}").status_code == 200

    state["active_user"] = state["doctor_b"]
    assert client.get(f"/api/v1/patients/{patient_id}").status_code == 404
    assert client.get("/api/v1/patients?search=NEW-SYNTHETIC").json()["items"] == []

    state["active_user"] = state["admin"]
    assert client.get(f"/api/v1/patients/{patient_id}").status_code == 200


def test_deleted_patient_is_not_listed(access_client, pg_engine):
    client, state = access_client
    with Session(pg_engine) as session:
        from datetime import UTC, datetime

        patient = session.get(Patient, state["owned"])
        patient.deleted_at = datetime.now(UTC)
        session.commit()

    assert client.get("/api/v1/patients").json()["items"] == []
    assert client.get(f"/api/v1/patients/{state['owned']}").status_code == 404


def test_anonymous_patient_endpoints_require_authentication():
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/api/v1/patients").status_code == 401
        assert client.get("/api/v1/patients/example").status_code == 401
        assert client.post("/api/v1/patients", json={"alias": "X"}).status_code == 401
