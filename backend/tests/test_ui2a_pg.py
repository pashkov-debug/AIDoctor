"""UI-2A: PostgreSQL integration tests — исключительно aidoctor_test."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.encounter import Encounter
from app.models.history_event import HistoryEvent
from app.models.medical_record import MedicalObservation
from app.models.patient import Patient
from app.services.context_builder import ContextBuilder
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.scripts.seed_ui2a_synthetic import seed_patient_timeline


def test_seed_is_idempotent_safe_and_context_compatible(pg_engine) -> None:
    anchor = datetime(2026, 10, 23, tzinfo=UTC)
    with Session(pg_engine) as session:
        synthetic = Patient(alias="S-UI2A", demographics_json={"synthetic": True})
        nonsynthetic = Patient(alias="REAL-NOT-TOUCH", demographics_json={})
        session.add_all([synthetic, nonsynthetic])
        session.flush()
        first = seed_patient_timeline(session, synthetic, anchor)
        second = seed_patient_timeline(session, synthetic, anchor)
        assert first == {"visits": 4, "events": 6, "observations": 3}
        assert second == {"visits": 0, "events": 0, "observations": 0}
        assert (
            session.scalar(
                select(func.count(Encounter.id)).where(Encounter.patient_id == synthetic.id)
            )
            == 4
        )
        assert (
            session.scalar(
                select(func.count(HistoryEvent.id)).where(HistoryEvent.patient_id == synthetic.id)
            )
            == 6
        )
        assert (
            session.scalar(
                select(func.count(MedicalObservation.id)).where(
                    MedicalObservation.patient_id == synthetic.id
                )
            )
            == 3
        )
        assert ContextBuilder(session).build(synthetic.id).excluded_attachments_count == 0
        with pytest.raises(ValueError, match="несинтетическую"):
            seed_patient_timeline(session, nonsynthetic, anchor)
        assert (
            session.scalar(
                select(func.count(Encounter.id)).where(Encounter.patient_id == nonsynthetic.id)
            )
            == 0
        )
        session.commit()


def test_clinical_internal_routes_isolate_doctors_and_patients(pg_engine) -> None:
    with Session(pg_engine) as session:
        doctor = User(username="dr-ui2a", password_hash="x", role="doctor")
        stranger = User(username="stranger-ui2a", password_hash="x", role="doctor")
        patient_user = User(username="patient-ui2a", password_hash="x", role="patient")
        session.add_all([doctor, stranger, patient_user])
        session.flush()
        patient = Patient(
            alias="CLINICAL-DEMO",
            user_id=patient_user.id,
            demographics_json={"synthetic": True},
        )
        session.add(patient)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        session.add(
            HistoryEvent(
                patient_id=patient.id,
                category="note",
                fact_json={"text": "Internal"},
                source_ref="synthetic:ui2a:internal",
            )
        )
        session.flush()
        record = Encounter(patient_id=patient.id, reason="initial", payload_json={})
        session.add(record)
        session.commit()
        pid, eid = patient.id, record.id
        actors = {
            "doctor": SimpleNamespace(id=doctor.id, role="doctor"),
            "stranger": SimpleNamespace(id=stranger.id, role="doctor"),
            "patient": SimpleNamespace(id=patient_user.id, role="patient"),
        }
    current = {"actor": actors["doctor"]}
    app = create_app()

    def override_db():
        with Session(pg_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[current_user] = lambda: current["actor"]
    try:
        with TestClient(app) as client:
            paths = [
                f"/api/v1/patients/{pid}/encounters",
                f"/api/v1/patients/{pid}/history-events",
                f"/api/v1/encounters/{eid}",
            ]
            for path in paths:
                assert client.get(path).status_code == 200
            assert (
                client.post(
                    f"/api/v1/patients/{pid}/encounters",
                    json={
                        "reason": "follow_up",
                        "complaints": ["Беспокойство"],
                    },
                ).status_code
                == 201
            )
            current["actor"] = actors["stranger"]
            for path in paths:
                assert client.get(path).status_code == 404
            current["actor"] = actors["patient"]
            for path in paths:
                assert client.get(path).status_code == 403
            assert (
                client.post(
                    f"/api/v1/patients/{pid}/encounters", json={"reason": "follow_up"}
                ).status_code
                == 403
            )
    finally:
        app.dependency_overrides.clear()
