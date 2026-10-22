"""Публикация и права — только на выделенной PostgreSQL-базе aidoctor_test."""

from types import SimpleNamespace

from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.clinical_publication import ClinicalPublication, ClinicalPublicationAudit
from app.models.history_event import HistoryEvent
from app.models.patient import Patient
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def test_ui2c_publication_and_role_isolation(pg_engine):
    with Session(pg_engine) as db:
        doctor = User(username="dr-ui2c", password_hash="x", role="doctor")
        stranger = User(username="stranger-ui2c", password_hash="x", role="doctor")
        owner = User(username="patient-ui2c", password_hash="x", role="patient")
        other = User(username="other-ui2c", password_hash="x", role="patient")
        admin = User(username="admin-ui2c", password_hash="x", role="admin")
        db.add_all([doctor, stranger, owner, other, admin])
        db.flush()
        patient = Patient(alias="S-1", user_id=owner.id, demographics_json={"synthetic": True})
        another = Patient(alias="S-2", user_id=other.id, demographics_json={"synthetic": True})
        db.add_all([patient, another])
        db.flush()
        db.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        event = HistoryEvent(
            patient_id=patient.id,
            category="symptom",
            fact_json={"text": "ВНУТРЕННЕЕ: не раскрывать пациенту"},
            source_ref="synthetic:ui2c",
        )
        db.add(event)
        db.commit()
        pid, eid = patient.id, event.id
        actors = {
            "doctor": SimpleNamespace(id=doctor.id, role="doctor"),
            "stranger": SimpleNamespace(id=stranger.id, role="doctor"),
            "patient": SimpleNamespace(id=owner.id, role="patient"),
            "other": SimpleNamespace(id=other.id, role="patient"),
            "admin": SimpleNamespace(id=admin.id, role="admin"),
        }

    selected = {"actor": actors["doctor"]}
    app = create_app()

    def db_override():
        with Session(pg_engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[current_user] = lambda: selected["actor"]
    base = f"/api/v1/patients/{pid}"
    patient_url = "/api/v1/patients/me/clinical-publications"
    try:
        with TestClient(app) as client:
            selected["actor"] = actors["patient"]
            assert client.get(patient_url).json() == {"items": [], "total": 0}
            assert client.get(base + "/clinical-publications").status_code == 403
            assert client.post(base + f"/history-events/{eid}/confirm").status_code == 403
            selected["actor"] = actors["stranger"]
            assert client.get(base + "/clinical-publications").status_code == 404
            assert client.post(base + f"/history-events/{eid}/confirm").status_code == 404
            selected["actor"] = actors["admin"]
            assert client.post(base + f"/history-events/{eid}/confirm").status_code == 403

            selected["actor"] = actors["doctor"]
            assert client.get(base + "/clinical-publications").json() == []
            assert client.post(base + "/history-events/not-real/confirm").status_code == 404
            approved = client.post(base + f"/history-events/{eid}/confirm")
            assert approved.status_code == 201, approved.text
            publication = approved.json()
            record_id = publication["id"]
            assert publication["status"] == "confirmed"
            assert publication["patient_text"] is None
            assert client.post(base + f"/history-events/{eid}/confirm").status_code == 409

            selected["actor"] = actors["patient"]
            assert client.get(patient_url).json() == {"items": [], "total": 0}
            selected["actor"] = actors["doctor"]
            publication_url = base + f"/clinical-publications/{record_id}"
            assert (
                client.post(
                    publication_url + "/publish",
                    json={
                        "expected_version": 1,
                        "patient_text": "Разрешённая запись",
                        "confirm_patient_visibility": False,
                    },
                ).status_code
                == 422
            )
            assert (
                client.post(
                    publication_url + "/publish",
                    json={
                        "expected_version": 0,
                        "patient_text": "Разрешённая запись",
                        "confirm_patient_visibility": True,
                    },
                ).status_code
                == 422
            )
            assert (
                client.post(
                    publication_url + "/publish",
                    json={
                        "expected_version": 1,
                        "patient_text": "Разрешённая запись",
                        "confirm_patient_visibility": True,
                    },
                ).status_code
                == 200
            )
            assert (
                client.post(
                    publication_url + "/publish",
                    json={
                        "expected_version": 1,
                        "patient_text": "Повторная запись",
                        "confirm_patient_visibility": True,
                    },
                ).status_code
                == 409
            )
            selected["actor"] = actors["other"]
            assert client.get(patient_url).json() == {"items": [], "total": 0}
            selected["actor"] = actors["patient"]
            own_data = client.get(patient_url).json()
            assert own_data["total"] == 1
            assert own_data["items"][0]["text"] == "Разрешённая запись"
            assert "ВНУТРЕННЕЕ" not in str(own_data)
            assert "history_event_id" not in str(own_data)
            assert client.get(base + "/history-events").status_code == 403

            selected["actor"] = actors["doctor"]
            assert (
                client.post(
                    publication_url + "/revoke",
                    json={
                        "expected_version": 1,
                        "reason": "Неактуальные сведения",
                    },
                ).status_code
                == 409
            )
            revoked = client.post(
                publication_url + "/revoke",
                json={
                    "expected_version": 2,
                    "reason": "Неактуальные сведения",
                },
            )
            assert revoked.status_code == 200
            assert revoked.json()["version"] == 3
            assert revoked.json()["status"] == "revoked"
            assert (
                client.post(
                    publication_url + "/publish",
                    json={
                        "expected_version": 3,
                        "patient_text": "Недопустимо",
                        "confirm_patient_visibility": True,
                    },
                ).status_code
                == 409
            )
            selected["actor"] = actors["patient"]
            assert client.get(patient_url).json()["total"] == 0

        with Session(pg_engine) as db:
            assert db.scalar(select(func.count(ClinicalPublication.id))) == 1
            assert [
                x.action
                for x in db.scalars(
                    select(ClinicalPublicationAudit).order_by(ClinicalPublicationAudit.version)
                ).all()
            ] == ["confirmed", "published", "revoked"]
    finally:
        app.dependency_overrides.clear()


def test_corrected_source_never_shown_as_active(pg_engine):
    with Session(pg_engine) as db:
        doctor = User(username="doc-2", role="doctor", password_hash="x")
        patient_user = User(username="pt-2", role="patient", password_hash="x")
        db.add_all([doctor, patient_user])
        db.flush()
        patient = Patient(alias="Коррекция", user_id=patient_user.id)
        db.add(patient)
        db.flush()
        db.add(DoctorPatient(patient_id=patient.id, doctor_id=doctor.id))
        event = HistoryEvent(
            patient_id=patient.id,
            category="note",
            fact_json={"text": "До правки"},
            source_ref="test:orig",
        )
        db.add(event)
        db.commit()
        pid, eid = patient.id, event.id
        did, uid = doctor.id, patient_user.id

    selected = {"actor": SimpleNamespace(id=did, role="doctor")}
    app = create_app()

    def db_override():
        with Session(pg_engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[current_user] = lambda: selected["actor"]
    try:
        with TestClient(app) as client:
            base = f"/api/v1/patients/{pid}"
            approval = client.post(base + f"/history-events/{eid}/confirm")
            assert approval.status_code == 201
            record = approval.json()
            assert (
                client.post(
                    base + f"/clinical-publications/{record['id']}/publish",
                    json={
                        "expected_version": 1,
                        "patient_text": "Ранее опубликованная запись",
                        "confirm_patient_visibility": True,
                    },
                ).status_code
                == 200
            )
            selected["actor"] = SimpleNamespace(id=uid, role="patient")
            assert client.get("/api/v1/patients/me/clinical-publications").json()["total"] == 1
            with Session(pg_engine) as db:
                db.add(
                    HistoryEvent(
                        patient_id=pid,
                        category="note",
                        fact_json={"text": "После правки"},
                        source_ref="test:corrected",
                        supersedes_id=eid,
                        correction_reason="Исправление",
                    )
                )
                db.commit()
            assert client.get("/api/v1/patients/me/clinical-publications").json()["total"] == 0
            selected["actor"] = SimpleNamespace(id=did, role="doctor")
            assert client.post(base + f"/history-events/{eid}/confirm").status_code == 409
    finally:
        app.dependency_overrides.clear()
