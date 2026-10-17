"""Контекст читает факты, не интерпретирует их и не читает вложения."""

from collections.abc import Iterator

import pytest
from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.encounter import Encounter
from app.models.history_event import HistoryEvent
from app.models.medical_record import MedicalAttachment, MedicalObservation
from app.models.patient import Patient
from app.models.questionnaire_response import QuestionnaireResponse
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture
def context_client(pg_engine) -> Iterator[tuple[TestClient, dict]]:
    with Session(pg_engine) as db:
        doctor = User(username="ctx-dr", password_hash="x", role="doctor")
        stranger = User(username="ctx-other", password_hash="x", role="doctor")
        patient_user = User(username="ctx-pat", password_hash="x", role="patient")
        db.add_all([doctor, stranger, patient_user])
        db.flush()

        patient = Patient(
            alias="SYNTHETIC-CONTEXT",
            demographics_json={},
            user_id=patient_user.id,
        )
        db.add(patient)
        db.flush()
        db.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        encounter = Encounter(patient_id=patient.id, reason="visit", payload_json={"note": "test"})
        db.add(encounter)
        db.flush()
        old_event = HistoryEvent(
            patient_id=patient.id, category="symptom",
            fact_json={"text": "outdated"},
            source_ref="synthetic:old",
        )
        old_observation = MedicalObservation(
            patient_id=patient.id,
            code="BP",
            value_json={"value": 100},
            source_ref="synthetic:old-observation",
        )
        db.add_all([old_event, old_observation])
        db.flush()
        new_event = HistoryEvent(
            patient_id=patient.id, category="symptom",
            fact_json={"text": "corrected"},
            source_ref="synthetic:new",
            supersedes_id=old_event.id,
        )
        new_observation = MedicalObservation(
            patient_id=patient.id,
            code="BP",
            value_json={"value": 120},
            supersedes_id=old_observation.id,
        )
        db.add_all([
            new_event,
            new_observation,
            QuestionnaireResponse(
                patient_id=patient.id,
                encounter_id=encounter.id,
                scale_id="SYNTHETIC",
                item_scores_json=[1, 2],
                total_score=3,
            ),
            MedicalAttachment(
                patient_id=patient.id,
                uploaded_by_id=doctor.id,
                filename="confidential.pdf",
                media_type="application/pdf",
                content_sha256="a" * 64,
                content_length=12,
                storage_key="synthetic-opaque-key",
                extraction_status="quarantined",
            ),
        ])
        state = {
            "patient_id": patient.id,
            "doctor_id": doctor.id,
            "stranger_id": stranger.id,
            "patient_user_id": patient_user.id,
            "active_user": doctor.id,
        }
        db.commit()

    def get_db_override():
        with Session(pg_engine) as db:
            yield db

    def user_override():
        with Session(pg_engine) as db:
            return db.get(User, state["active_user"])

    app = create_app()
    app.dependency_overrides[get_db] = get_db_override
    app.dependency_overrides[current_user] = user_override
    try:
        with TestClient(app) as client:
            yield client, state
    finally:
        app.dependency_overrides.clear()


def test_context_is_versioned_reproducible_and_excludes_superseded_data(context_client):
    client, state = context_client
    path = f"/api/v1/patients/{state['patient_id']}/context"
    response = client.get(path)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["schema_version"] == "1.0"
    assert body["patient_id"] == state["patient_id"]
    assert body["excluded_attachments_count"] == 1
    assert len(body["content_sha256"]) == 64
    assert len(body["items"]) == 4
    assert {item["kind"] for item in body["items"]} == {
        "encounter", "history_event", "observation", "questionnaire"
    }
    serialized = response.text
    assert "outdated" not in serialized
    assert '"value":100' not in serialized.replace(" ", "")
    assert "corrected" in serialized
    assert "confidential.pdf" not in serialized
    assert "synthetic-opaque-key" not in serialized
    assert client.get(path).json()["content_sha256"] == body["content_sha256"]


def test_context_denies_unlinked_doctor_and_patient(context_client):
    client, state = context_client
    path = f"/api/v1/patients/{state['patient_id']}/context"
    state["active_user"] = state["stranger_id"]
    assert client.get(path).status_code == 404
    state["active_user"] = state["patient_user_id"]
    assert client.get(path).status_code == 403


def test_anonymous_context_requires_authentication():
    with TestClient(create_app()) as client:
        assert client.get("/api/v1/patients/example/context").status_code == 401
