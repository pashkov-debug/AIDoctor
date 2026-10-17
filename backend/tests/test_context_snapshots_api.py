"""Интеграционные тесты версионирования контекста на PostgreSQL."""

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
def snapshot_api(pg_engine) -> Iterator[tuple[TestClient, dict[str, str]]]:
    with Session(pg_engine) as db:
        doctor = User(username="snapshot-dr", password_hash="x", role="doctor")
        stranger = User(username="snapshot-stranger", password_hash="x", role="doctor")
        db.add_all([doctor, stranger])
        db.flush()
        patient = Patient(alias="SYNTHETIC-SNAPSHOT", demographics_json={})
        db.add(patient)
        db.flush()
        db.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        state = {
            "doctor": doctor.id,
            "stranger": stranger.id,
            "patient": patient.id,
            "active": doctor.id,
        }
        db.commit()

    def override_db():
        with Session(pg_engine) as db:
            yield db

    def override_user():
        with Session(pg_engine) as db:
            return db.get(User, state["active"])

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[current_user] = override_user
    try:
        with TestClient(app) as client:
            yield client, state
    finally:
        app.dependency_overrides.clear()


def test_create_list_read_snapshot(snapshot_api):
    client, state = snapshot_api
    base = f"/api/v1/patients/{state['patient']}/context"
    created = client.post(f"{base}/snapshots")
    assert created.status_code == 201, created.text
    summary = created.json()
    assert summary["patient_id"] == state["patient"]
    assert summary["fact_count"] == 0
    assert summary["created_by_id"] == state["doctor"]

    result = client.get(f"{base}/snapshots")
    assert result.status_code == 200, result.text
    assert [entry["id"] for entry in result.json()] == [summary["id"]]

    detail = client.get(f"{base}/snapshots/{summary['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["context"]["content_sha256"] == summary["content_sha256"]
    assert detail.json()["snapshot"]["id"] == summary["id"]

    same = client.post(f"{base}/snapshots/{summary['id']}/delta")
    assert same.status_code == 200, same.text
    assert same.json()["changed"] is False


def test_server_delta_from_persisted_snapshot(snapshot_api, pg_engine):
    client, state = snapshot_api
    base = f"/api/v1/patients/{state['patient']}/context"
    saved = client.post(f"{base}/snapshots")
    assert saved.status_code == 201, saved.text
    snapshot_id = saved.json()["id"]

    with Session(pg_engine) as db:
        db.add(
            HistoryEvent(
                patient_id=state["patient"],
                category="synthetic",
                fact_json={"text": "synthetic observation"},
                source_ref="test:snapshot",
            )
        )
        db.commit()

    difference = client.post(f"{base}/snapshots/{snapshot_id}/delta")
    assert difference.status_code == 200, difference.text
    delta = difference.json()
    assert delta["changed"] is True
    assert len(delta["added"]) == 1
    assert delta["added"][0]["payload"]["fact"]["text"] == "synthetic observation"
    assert delta["before_fact_count"] == 0
    assert delta["after_fact_count"] == 1

    original = client.get(f"{base}/snapshots/{snapshot_id}")
    assert original.json()["context"]["items"] == []


def test_stranger_cannot_create_list_read_or_compare(snapshot_api):
    client, state = snapshot_api
    base = f"/api/v1/patients/{state['patient']}/context"
    created = client.post(f"{base}/snapshots")
    assert created.status_code == 201
    snapshot_id = created.json()["id"]

    state["active"] = state["stranger"]
    assert client.post(f"{base}/snapshots").status_code == 404
    assert client.get(f"{base}/snapshots").status_code == 404
    assert client.get(f"{base}/snapshots/{snapshot_id}").status_code == 404
    assert client.post(f"{base}/snapshots/{snapshot_id}/delta").status_code == 404


def test_missing_snapshot_returns_404(snapshot_api):
    client, state = snapshot_api
    base = f"/api/v1/patients/{state['patient']}/context"
    assert client.get(f"{base}/snapshots/not-found").status_code == 404
    assert client.post(f"{base}/snapshots/not-found/delta").status_code == 404


def test_unauthenticated_requests_are_rejected():
    with TestClient(create_app()) as client:
        base = "/api/v1/patients/unknown/context/snapshots"
        assert client.get(base).status_code == 401
        assert client.post(base).status_code == 401
        assert client.get(f"{base}/unknown").status_code == 401
        assert client.post(f"{base}/unknown/delta").status_code == 401
