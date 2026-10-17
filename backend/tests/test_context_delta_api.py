"""Интеграционная проверка Digest/Delta на PostgreSQL и уровне доступа."""

from collections.abc import Iterator

import pytest
from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.history_event import HistoryEvent
from app.models.patient import Patient
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def delta_api(pg_engine) -> Iterator[tuple[TestClient, dict[str, str]]]:
    with Session(pg_engine) as db:
        doctor = User(username="delta-dr", password_hash="x", role="doctor")
        stranger = User(username="delta-stranger", password_hash="x", role="doctor")
        db.add_all([doctor, stranger])
        db.flush()
        patient = Patient(alias="DELTA-SYNTHETIC", demographics_json={})
        db.add(patient)
        db.flush()
        db.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        state = {"doctor": doctor.id, "stranger": stranger.id, "patient": patient.id}
        state["active"] = doctor.id
        db.commit()

    def get_db_override():
        with Session(pg_engine) as db:
            yield db

    def user_override():
        with Session(pg_engine) as db:
            return db.get(User, state["active"])

    app = create_app()
    app.dependency_overrides[get_db] = get_db_override
    app.dependency_overrides[current_user] = user_override
    try:
        with TestClient(app) as client:
            yield client, state
    finally:
        app.dependency_overrides.clear()


def test_digest_and_delta_with_new_history_event(delta_api, pg_engine):
    client, state = delta_api
    base_url = f"/api/v1/patients/{state['patient']}/context"
    baseline_response = client.get(base_url)
    assert baseline_response.status_code == 200, baseline_response.text
    baseline = baseline_response.json()

    digest = client.get(f"{base_url}/digest")
    assert digest.status_code == 200, digest.text
    assert digest.json()["context_sha256"] == baseline["content_sha256"]
    assert digest.json()["total_facts"] == len(baseline["items"])

    with Session(pg_engine) as db:
        db.add(
            HistoryEvent(
                patient_id=state["patient"],
                category="synthetic",
                fact_json={"text": "new synthetic fact"},
                source_ref="integration:test",
            )
        )
        db.commit()

    result = client.post(f"{base_url}/delta", json={"baseline": baseline})
    assert result.status_code == 200, result.text
    delta = result.json()
    assert delta["changed"] is True
    assert len(delta["added"]) == 1
    assert delta["added"][0]["kind"] == "history_event"
    assert delta["added"][0]["payload"]["fact"]["text"] == "new synthetic fact"

    current = client.get(base_url).json()
    same = client.post(f"{base_url}/delta", json={"baseline": current})
    assert same.status_code == 200
    assert same.json()["changed"] is False


def test_doctor_without_link_does_not_access_digest_or_delta(delta_api):
    client, state = delta_api
    state["active"] = state["stranger"]
    base_url = f"/api/v1/patients/{state['patient']}/context"
    assert client.get(f"{base_url}/digest").status_code == 404
    assert client.post(f"{base_url}/delta", json={"baseline": {}}).status_code == 404


def test_missing_token_denied_before_medical_data():
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/patients/unknown/context/digest").status_code == 401
        assert client.post(
            "/api/v1/patients/unknown/context/delta", json={"baseline": {}}
        ).status_code == 401


def test_invalid_snapshot_returns_422(delta_api):
    client, state = delta_api
    endpoint = f"/api/v1/patients/{state['patient']}/context"
    baseline = client.get(endpoint).json()
    baseline["content_sha256"] = "0" * 64
    result = client.post(f"{endpoint}/delta", json={"baseline": baseline})
    assert result.status_code == 422
