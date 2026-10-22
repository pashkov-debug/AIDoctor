"""UI-2B: PostgreSQL-интеграция только на aidoctor_test."""

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
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.scripts.seed_ui2a_synthetic import seed_patient_timeline
from backend.scripts.seed_ui2b_synthetic import (
    FIRST_EVENTS,
    FIRST_OBSERVATIONS,
    FIRST_VISITS,
    SECOND_EVENTS,
    SECOND_OBSERVATIONS,
    SECOND_VISITS,
    get_or_create_second_patient,
    seed_extra_records,
)


def test_two_idempotent_separate_timelines(pg_engine) -> None:
    anchor = datetime(2026, 10, 23, tzinfo=UTC)
    with Session(pg_engine) as session:
        doctor = User(username="ui2b-doctor", role="doctor", password_hash="x")
        session.add(doctor)
        session.flush()
        first = Patient(alias="UI2B-A", demographics_json={"synthetic": True})
        session.add(first)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id=first.id))
        session.flush()

        assert seed_patient_timeline(session, first, anchor)["visits"] == 4
        a = seed_extra_records(
            session,
            first,
            anchor,
            "anxiety",
            FIRST_VISITS,
            FIRST_EVENTS,
            FIRST_OBSERVATIONS,
        )
        second = get_or_create_second_patient(session, doctor)
        b = seed_extra_records(
            session,
            second,
            anchor,
            "mood",
            SECOND_VISITS,
            SECOND_EVENTS,
            SECOND_OBSERVATIONS,
        )
        assert a == {
            "visits": len(FIRST_VISITS),
            "events": len(FIRST_EVENTS),
            "observations": len(FIRST_OBSERVATIONS),
        }
        assert b == {
            "visits": len(SECOND_VISITS),
            "events": len(SECOND_EVENTS),
            "observations": len(SECOND_OBSERVATIONS),
        }
        assert seed_patient_timeline(session, first, anchor) == {
            "visits": 0,
            "events": 0,
            "observations": 0,
        }
        assert seed_extra_records(
            session,
            first,
            anchor,
            "anxiety",
            FIRST_VISITS,
            FIRST_EVENTS,
            FIRST_OBSERVATIONS,
        ) == {"visits": 0, "events": 0, "observations": 0}
        again = get_or_create_second_patient(session, doctor)
        assert again.id == second.id
        assert seed_extra_records(
            session,
            second,
            anchor,
            "mood",
            SECOND_VISITS,
            SECOND_EVENTS,
            SECOND_OBSERVATIONS,
        ) == {"visits": 0, "events": 0, "observations": 0}
        assert session.scalar(
            select(func.count(Encounter.id)).where(Encounter.patient_id == first.id)
        ) == 4 + len(FIRST_VISITS)
        assert session.scalar(
            select(func.count(Encounter.id)).where(Encounter.patient_id == second.id)
        ) == len(SECOND_VISITS)
        assert session.scalar(
            select(func.count(HistoryEvent.id)).where(HistoryEvent.patient_id == first.id)
        ) == 6 + len(FIRST_EVENTS)
        assert session.scalar(
            select(func.count(MedicalObservation.id)).where(
                MedicalObservation.patient_id == second.id
            )
        ) == len(SECOND_OBSERVATIONS)
        session.commit()


def test_unmarked_patient_cannot_receive_seed(pg_engine) -> None:
    with Session(pg_engine) as session:
        other = Patient(alias="NOT-SYNTHETIC", demographics_json={})
        session.add(other)
        session.flush()
        with pytest.raises(ValueError, match="synthetic"):
            seed_extra_records(
                session,
                other,
                datetime(2026, 10, 23, tzinfo=UTC),
                "mood",
                SECOND_VISITS,
                SECOND_EVENTS,
                SECOND_OBSERVATIONS,
            )
        assert (
            session.scalar(select(func.count(Encounter.id)).where(Encounter.patient_id == other.id))
            == 0
        )


def test_patient_cannot_read_doctor_visits_history_or_context(pg_engine) -> None:
    with Session(pg_engine) as session:
        doctor = User(username="dr-ui2b", password_hash="x", role="doctor")
        patient_user = User(username="patient-ui2b", password_hash="x", role="patient")
        session.add_all([doctor, patient_user])
        session.flush()
        patient = Patient(
            alias="UI2B-PORTAL",
            user_id=patient_user.id,
            demographics_json={"synthetic": True},
        )
        session.add(patient)
        session.flush()
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        session.commit()
        pid = patient.id
        actors = {
            "doctor": SimpleNamespace(id=doctor.id, role="doctor"),
            "patient": SimpleNamespace(id=patient_user.id, role="patient"),
        }
    app = create_app()
    actor = {"value": actors["doctor"]}

    def override_db():
        with Session(pg_engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[current_user] = lambda: actor["value"]
    try:
        with TestClient(app) as client:
            for path in (
                f"/api/v1/patients/{pid}/encounters",
                f"/api/v1/patients/{pid}/history-events",
                f"/api/v1/patients/{pid}/context",
                f"/api/v1/patients/{pid}/context/digest",
            ):
                assert client.get(path).status_code == 200
                actor["value"] = actors["patient"]
                assert client.get(path).status_code == 403
                actor["value"] = actors["doctor"]
            actor["value"] = actors["patient"]
            assert client.get("/api/v1/patients/me/portal").status_code == 200
    finally:
        app.dependency_overrides.clear()
