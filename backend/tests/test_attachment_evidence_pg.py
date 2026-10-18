"""Интеграция этапа 6.1: только локальная PostgreSQL *_test."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.attachment_evidence_draft import (
    AttachmentEvidenceDraft,
    AttachmentEvidenceReadAudit,
)
from app.models.medical_record import MedicalAttachment
from app.models.patient import Patient
from app.services.context_builder import ContextBuilder
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


@pytest.fixture
def evidence_case(pg_engine):
    with Session(pg_engine) as db:
        doctor = User(username="evidence-doc", password_hash="synthetic", role="doctor")
        stranger = User(username="evidence-other", password_hash="synthetic", role="doctor")
        admin = User(username="evidence-admin", password_hash="synthetic", role="admin")
        patient_user = User(username="evidence-patient", password_hash="synthetic", role="patient")
        db.add_all([doctor, stranger, admin, patient_user])
        db.flush()
        patient = Patient(alias="SYNTHETIC-EVIDENCE", demographics_json={}, user_id=patient_user.id)
        other_patient = Patient(alias="SYNTHETIC-OTHER", demographics_json={})
        db.add_all([patient, other_patient])
        db.flush()
        link = DoctorPatient(doctor_id=doctor.id, patient_id=patient.id)
        db.add(link)
        db.flush()
        attachment = MedicalAttachment(
            patient_id=patient.id,
            uploaded_by_id=doctor.id,
            filename="synthetic.pdf",
            media_type="application/pdf",
            content_sha256="a" * 64,
            content_length=20,
            storage_key="synthetic-key-not-a-real-file",
            extraction_status="quarantined",
        )
        other_attachment = MedicalAttachment(
            patient_id=other_patient.id,
            uploaded_by_id=doctor.id,
            filename="other.pdf",
            media_type="application/pdf",
            content_sha256="b" * 64,
            content_length=21,
            storage_key="synthetic-other-file",
            extraction_status="quarantined",
        )
        db.add_all([attachment, other_attachment])
        db.flush()
        state = {
            "doctor": doctor.id,
            "stranger": stranger.id,
            "admin": admin.id,
            "patient_user": patient_user.id,
            "patient": patient.id,
            "other_patient": other_patient.id,
            "attachment": attachment.id,
            "other_attachment": other_attachment.id,
            "link": link.id,
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


def _endpoint(state):
    return (
        f"/api/v1/patients/{state['patient']}"
        f"/attachments/{state['attachment']}/evidence-drafts"
    )


def _payload():
    return {"source_locator": "  стр. 2 ", "excerpt": "  Синтетический фрагмент. "}


def test_manual_provenance_dedup_and_context_isolation(evidence_case, pg_engine):
    client, state = evidence_case
    url = _endpoint(state)
    first = client.post(url, json=_payload())
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["source_kind"] == "manual"
    assert body["verification_status"] == "unverified"
    assert body["source_locator"] == "стр. 2"
    assert body["excerpt"] == "Синтетический фрагмент."
    assert body["attachment_sha256"] == "a" * 64
    assert body["excerpt_sha256"] == hashlib.sha256(body["excerpt"].encode()).hexdigest()
    assert first.headers["cache-control"] == "private, no-store"

    repeated = client.post(url, json={
        "source_locator": "стр. 2", "excerpt": "Синтетический фрагмент."
    })
    assert repeated.status_code == 201
    assert repeated.json()["id"] == body["id"]
    listed = client.get(url)
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "private, no-store"
    assert len(listed.json()) == 1

    with Session(pg_engine) as db:
        assert db.scalar(select(func.count(AttachmentEvidenceDraft.id))) == 1
        assert db.scalar(select(func.count(AttachmentEvidenceReadAudit.id))) == 1
        assert db.scalar(select(AttachmentEvidenceReadAudit.returned_count)) == 1
        context = ContextBuilder(db).build(state["patient"])
        assert context.items == []
        assert context.excluded_attachments_count == 1
        assert db.get(MedicalAttachment, state["attachment"]).extraction_status == "quarantined"


def test_access_and_cross_patient_boundaries(evidence_case, pg_engine):
    client, state = evidence_case
    url = _endpoint(state)
    assert client.post(url, json=_payload()).status_code == 201

    state["active"] = state["stranger"]
    assert client.post(url, json=_payload()).status_code == 404
    assert client.get(url).status_code == 404
    state["active"] = state["patient_user"]
    assert client.get(url).status_code == 403
    assert client.post(url, json=_payload()).status_code == 403
    state["active"] = state["admin"]
    assert client.get(url).status_code == 403
    assert client.post(url, json=_payload()).status_code == 403
    state["active"] = state["doctor"]
    wrong = (
        f"/api/v1/patients/{state['patient']}/attachments/"
        f"{state['other_attachment']}/evidence-drafts"
    )
    assert client.get(wrong).status_code == 404
    assert client.post(wrong, json=_payload()).status_code == 404

    with Session(pg_engine) as db:
        db.query(DoctorPatient).filter_by(id=state["link"]).delete()
        db.commit()
    assert client.get(url).status_code == 404
    assert client.post(url, json=_payload()).status_code == 404


def test_soft_deleted_patient_denied(evidence_case, pg_engine):
    client, state = evidence_case
    from app.db.base import utc_now

    with Session(pg_engine) as db:
        patient = db.get(Patient, state["patient"])
        patient.deleted_at = utc_now()
        db.commit()
    assert client.get(_endpoint(state)).status_code == 404
    assert client.post(_endpoint(state), json=_payload()).status_code == 404


def test_validation_and_no_db_side_effects(evidence_case, pg_engine):
    client, state = evidence_case
    url = _endpoint(state)
    for payload in (
        {"source_locator": " ", "excerpt": "Valid"},
        {"source_locator": "стр. 1", "excerpt": "\x00"},
        {"source_locator": "стр. 1", "excerpt": "x" * 2001},
        {"source_locator": "стр. 1", "excerpt": "Valid", "approved": True},
    ):
        result = client.post(url, json=payload)
        assert result.status_code == 422, result.text
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count(AttachmentEvidenceDraft.id))) == 0


def test_parallel_post_creates_single_row(evidence_case, pg_engine):
    _, state = evidence_case
    from app.models.medical_record import MedicalAttachment
    from app.services.attachment_evidence import create_manual_draft

    barrier = Barrier(2)

    def work(_):
        with Session(pg_engine) as db:
            attachment = db.get(MedicalAttachment, state["attachment"])
            barrier.wait(timeout=10)
            return create_manual_draft(
                db,
                attachment=attachment,
                actor_id=state["doctor"],
                source_locator="стр. 3",
                excerpt="synthetic proof",
            ).id

    with ThreadPoolExecutor(max_workers=2) as executor:
        ids = list(executor.map(work, range(2)))
    assert ids[0] == ids[1]
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count(AttachmentEvidenceDraft.id))) == 1


def test_unauthenticated_requests_require_token():
    with TestClient(create_app()) as client:
        path = "/api/v1/patients/unknown/attachments/unknown/evidence-drafts"
        assert client.get(path).status_code == 401
        assert client.post(path, json=_payload()).status_code == 401



def test_empty_read_is_audited(evidence_case, pg_engine):
    client, state = evidence_case
    response = client.get(_endpoint(state))
    assert response.status_code == 200
    assert response.json() == []
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count(AttachmentEvidenceReadAudit.id))) == 1
        assert db.scalar(select(AttachmentEvidenceReadAudit.returned_count)) == 0
