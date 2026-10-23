"""UI-4A: PostgreSQL, изоляция, неизменяемые snapshots, идемпотентность."""

from types import SimpleNamespace
from uuid import uuid4

from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.ai_workspace import AIRequest, AIRequestAudit
from app.models.context_snapshot import ContextSnapshot
from app.models.medical_record import MedicalAttachment
from app.models.patient import Patient
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def test_prepare_and_authorize(pg_engine):
    with Session(pg_engine) as db:
        doctor = User(username="dr4a", role="doctor", password_hash="x")
        other_doctor = User(username="dr4aOther", role="doctor", password_hash="x")
        patient_actor = User(username="pt4a", role="patient", password_hash="x")
        admin = User(username="ad4a", role="admin", password_hash="x")
        db.add_all([doctor, other_doctor, patient_actor, admin])
        db.flush()
        patient = Patient(
            alias="Синтетический 4A",
            user_id=patient_actor.id,
            demographics_json={"synthetic": True},
        )
        other_patient = Patient(alias="Другой пациент")
        db.add_all([patient, other_patient])
        db.flush()
        db.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        attachment = MedicalAttachment(
            patient_id=patient.id,
            uploaded_by_id=doctor.id,
            filename="quarantine.pdf",
            media_type="application/pdf",
            content_length=100,
            content_sha256="a" * 64,
            storage_key="test/attachment",
            extraction_status="quarantined",
        )
        db.add(attachment)
        db.commit()
        pid, other_pid, aid = patient.id, other_patient.id, attachment.id
        actors = {
            name: SimpleNamespace(id=user.id, role=user.role)
            for name, user in {
                "doctor": doctor,
                "other_doctor": other_doctor,
                "patient": patient_actor,
                "admin": admin,
            }.items()
        }

    current = {"user": actors["doctor"]}
    application = create_app()

    def db_override():
        with Session(pg_engine) as session:
            yield session

    application.dependency_overrides[get_db] = db_override
    application.dependency_overrides[current_user] = lambda: current["user"]
    endpoint = f"/api/v1/patients/{pid}/ai-requests"
    payload = {
        "question": "Оцените динамику жалоб пациента с учётом истории",
        "request_key": str(uuid4()),
        "attachment_ids": [aid],
    }
    try:
        with TestClient(application) as client:
            current["user"] = actors["patient"]
            assert client.get(endpoint).status_code == 403
            assert client.post(endpoint, json=payload).status_code == 403
            current["user"] = actors["admin"]
            assert client.get(endpoint).status_code == 403
            current["user"] = actors["other_doctor"]
            assert client.get(endpoint).status_code == 404
            assert client.post(endpoint, json=payload).status_code == 404

            current["user"] = actors["doctor"]
            assert client.get(f"/api/v1/patients/{other_pid}/ai-requests").status_code == 404
            bad = client.post(endpoint, json={**payload, "attachment_ids": [str(uuid4())]})
            assert bad.status_code == 404
            assert client.get(endpoint).json() == []

            created = client.post(endpoint, json=payload)
            assert created.status_code == 201, created.text
            item = created.json()
            assert item["status"] == "prepared"
            assert item["ai_response_available"] is False
            assert item["revision"] == 1
            assert item["doctor_context"]["schema_version"] == "doctor_context.v1"
            assert item["attachment_manifest"][0]["status"] == "excluded_unverified"
            assert "payload_json" not in item
            repeat = client.post(endpoint, json=payload)
            assert repeat.status_code == 201
            assert repeat.json()["id"] == item["id"]
            clash = client.post(endpoint, json={**payload, "question": "Иной вопрос для анализа"})
            assert clash.status_code == 409
            assert client.get(endpoint).json()[0]["id"] == item["id"]
            assert client.get(endpoint + "/" + item["id"]).status_code == 200
            current["user"] = actors["other_doctor"]
            assert client.get(endpoint + "/" + item["id"]).status_code == 404

        with Session(pg_engine) as db:
            assert db.scalar(select(func.count(AIRequest.id))) == 1
            assert db.scalar(select(func.count(AIRequestAudit.id))) == 1
            assert db.scalar(select(func.count(ContextSnapshot.id))) == 1
            snapshot = db.get(ContextSnapshot, item["context_snapshot_id"])
            assert snapshot.patient_id == pid
            assert snapshot.content_sha256 == item["context_sha256"]
    finally:
        application.dependency_overrides.clear()
