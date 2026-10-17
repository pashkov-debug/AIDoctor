"""Интеграционные проверки. Без TEST_DATABASE_URL тесты пропускаются."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.auth import current_user
from app.core.config import settings
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.patient import Patient


@pytest.fixture
def api(pg_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "attachments_dir", str(tmp_path))
    with Session(pg_engine) as db:
        doctor = User(username="doctor-file", password_hash="test", role="doctor")
        other = User(username="other-file", password_hash="test", role="doctor")
        patient_user = User(username="patient-file", password_hash="test", role="patient")
        db.add_all([doctor, other, patient_user])
        db.flush()
        patient_user_id = patient_user.id
        patient = Patient(alias="synthetic", demographics_json={}, user_id=patient_user_id)
        db.add(patient)
        db.flush()
        doctor_id, other_id, patient_id = doctor.id, other.id, patient.id
        db.add(DoctorPatient(doctor_id=doctor_id, patient_id=patient_id))
        db.commit()

    state = {"user_id": doctor_id}

    def override_session():
        with Session(pg_engine) as db:
            yield db

    def override_user():
        with Session(pg_engine) as db:
            return db.get(User, state["user_id"])

    app = create_app()
    app.dependency_overrides[get_db] = override_session
    app.dependency_overrides[current_user] = override_user
    with TestClient(app) as client:
        yield client, state, patient_id, other_id, patient_user_id
    app.dependency_overrides.clear()


def test_upload_list_download_and_access(api):
    client, state, patient_id, other_id, patient_user_id = api
    endpoint = f"/api/v1/patients/{patient_id}/attachments"
    payload = b"%PDF-1.7\nsynthetic clinical example"

    uploaded = client.post(endpoint, files={"file": ("study.pdf", payload, "application/pdf")})
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["extraction_status"] == "quarantined"
    assert body["media_type"] == "application/pdf"
    assert body["content_length"] == len(payload)
    assert len(client.get(endpoint).json()) == 1

    downloaded = client.get(f"{endpoint}/{body['id']}")
    assert downloaded.status_code == 200
    assert downloaded.content == payload
    assert "attachment" in downloaded.headers["content-disposition"]
    assert downloaded.headers["cache-control"] == "private, no-store"

    state["user_id"] = patient_user_id
    assert client.get(endpoint).status_code == 200
    assert client.get(f"{endpoint}/{body['id']}").content == payload

    state["user_id"] = other_id
    assert client.get(endpoint).status_code == 404
    assert client.get(f"{endpoint}/{body['id']}").status_code == 404
    assert client.post(
        endpoint, files={"file": ("study.pdf", payload, "application/pdf")}
    ).status_code == 404


def test_upload_rejects_fake_pdf(api):
    client, _, patient_id, _, _ = api
    endpoint = f"/api/v1/patients/{patient_id}/attachments"
    response = client.post(
        endpoint, files={"file": ("x.pdf", b"malicious", "application/pdf")}
    )
    assert response.status_code == 415
    assert client.get(endpoint).json() == []


def test_authentication_required():
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/patients/not-a-real-id/attachments")
    assert response.status_code == 401
