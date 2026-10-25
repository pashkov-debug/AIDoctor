"""Этап 1: доступ, изоляция, неизменяемый аудит в PostgreSQL."""

from types import SimpleNamespace

from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.clinical_entry_audit import ClinicalEntryAudit
from app.models.encounter import Encounter
from app.models.history_event import HistoryEvent
from app.models.medical_record import MedicalObservation
from app.models.patient import Patient
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def test_manual_entries_transactional_and_isolated(pg_engine):
    with Session(pg_engine) as db:
        doctor = User(username="ws1_doctor", role="doctor", password_hash="x")
        stranger = User(username="ws1_stranger", role="doctor", password_hash="x")
        patient_actor = User(username="ws1_patient_user", role="patient", password_hash="x")
        db.add_all([doctor, stranger, patient_actor])
        db.flush()
        patient = Patient(alias="Рабочая пациентка", demographics_json={})
        other = Patient(alias="Другая пациентка", demographics_json={})
        db.add_all([patient, other])
        db.flush()
        db.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        visit = Encounter(
            patient_id=patient.id, reason="первичный", status="draft", payload_json={}
        )
        db.add(visit)
        db.commit()
        patient_id, other_id, visit_id = patient.id, other.id, visit.id
        actors = {
            "doctor": SimpleNamespace(id=doctor.id, role="doctor"),
            "stranger": SimpleNamespace(id=stranger.id, role="doctor"),
            "patient": SimpleNamespace(id=patient_actor.id, role="patient"),
        }
    active = {"actor": actors["doctor"]}
    app = create_app()

    def override_db():
        with Session(pg_engine) as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[current_user] = lambda: active["actor"]
    base = f"/api/v1/patients/{patient_id}"
    try:
        with TestClient(app) as client:
            body = {
                "category": "symptom",
                "fact": {"text": "Тревога девять месяцев"},
                "encounter_id": visit_id,
                "occurred_at": "2026-08-03T10:00:00+03:00",
            }
            active["actor"] = actors["patient"]
            assert client.post(base + "/history-events", json=body).status_code == 403
            active["actor"] = actors["stranger"]
            assert client.post(base + "/history-events", json=body).status_code == 404
            active["actor"] = actors["doctor"]
            wrong = client.post(f"/api/v1/patients/{other_id}/history-events", json=body)
            assert wrong.status_code == 404
            created = client.post(base + "/history-events", json=body)
            assert created.status_code == 201, created.text
            assert created.json()["source_ref"] == f"doctor:{actors['doctor'].id}"
            assert created.json()["fact"] == body["fact"]
            assert client.get(base + "/history-events").json()["total"] == 1

            obs = {
                "encounter_id": visit_id,
                "code_system": "local",
                "code": "GAD-7",
                "value": {"score": 17, "maximum": 21},
                "observed_at": "2026-08-03T10:00:00+03:00",
            }
            response = client.post(base + "/observations", json=obs)
            assert response.status_code == 201, response.text
            assert response.json()["value"]["score"] == 17
            assert client.get(base + "/observations").json()["total"] == 1

            invalid = client.post(
                base + "/observations",
                json={**obs, "encounter_id": "00000000-0000-4000-8000-000000000000"},
            )
            assert invalid.status_code == 422
        with Session(pg_engine) as db:
            assert db.scalar(select(func.count(HistoryEvent.id))) == 1
            assert db.scalar(select(func.count(MedicalObservation.id))) == 1
            audits = db.scalars(select(ClinicalEntryAudit)).all()
            assert len(audits) == 2
            assert {x.record_type for x in audits} == {"history_event", "medical_observation"}
            assert all(x.actor_id == actors["doctor"].id for x in audits)
    finally:
        app.dependency_overrides.clear()
