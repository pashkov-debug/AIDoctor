"""PostgreSQL-контракт карантинной проверки: только выделенная БД *_test."""

import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.api.auth import current_user
from app.core.config import settings
from app.db.base import utc_now
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.attachment_security import AttachmentSecurityEvent, AttachmentSecurityReview
from app.models.medical_record import MedicalAttachment
from app.models.patient import Patient
from app.services.attachment_security import (
    InspectionUnavailable,
    perform_precheck,
    require_processing_clearance,
)
from app.services.attachment_storage import AttachmentStorage
from app.services.context_builder import ContextBuilder
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def security_case(pg_engine, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "attachments_dir", str(tmp_path))
    store = AttachmentStorage(tmp_path)
    payload = b"%PDF-1.7\nSYNTHETIC-STAGE-6.2"
    saved = store.save(io.BytesIO(payload), "synthetic.pdf")
    other_saved = store.save(io.BytesIO(payload), "other.pdf")
    with Session(pg_engine) as db:
        doctor = User(username="sec-doc", password_hash="synthetic", role="doctor")
        stranger = User(username="sec-other", password_hash="synthetic", role="doctor")
        admin = User(username="sec-admin", password_hash="synthetic", role="admin")
        patient_user = User(username="sec-patient", password_hash="synthetic", role="patient")
        db.add_all([doctor, stranger, admin, patient_user])
        db.flush()
        patient = Patient(alias="SYNTHETIC-6.2", demographics_json={}, user_id=patient_user.id)
        another_patient = Patient(alias="SYNTHETIC-OTHER", demographics_json={})
        db.add_all([patient, another_patient])
        db.flush()
        link = DoctorPatient(doctor_id=doctor.id, patient_id=patient.id)
        db.add(link)
        db.flush()
        attachment = MedicalAttachment(
            patient_id=patient.id,
            uploaded_by_id=doctor.id,
            filename=saved.filename,
            media_type=saved.media_type,
            content_sha256=saved.content_sha256,
            content_length=saved.content_length,
            storage_key=saved.key,
            extraction_status="quarantined",
        )
        other_attachment = MedicalAttachment(
            patient_id=another_patient.id,
            uploaded_by_id=admin.id,
            filename=other_saved.filename,
            media_type=other_saved.media_type,
            content_sha256=other_saved.content_sha256,
            content_length=other_saved.content_length,
            storage_key=other_saved.key,
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
            "attachment": attachment.id,
            "other_attachment": other_attachment.id,
            "link": link.id,
            "active": admin.id,
            "storage_key": saved.key,
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
            yield client, state, store, payload
    finally:
        app.dependency_overrides.clear()


def _url(state):
    return (
        f"/api/v1/patients/{state['patient']}/"
        f"attachments/{state['attachment']}/security"
    )


def test_quarantine_precheck_audit_and_context_isolation(security_case, pg_engine):
    client, state, _, _ = security_case
    url = _url(state)
    initial = client.get(url)
    assert initial.status_code == 200, initial.text
    assert initial.json()["status"] == "quarantined"
    assert initial.json()["checked_at"] is None
    checked = client.post(url + "/precheck")
    assert checked.status_code == 200, checked.text
    assert checked.headers["cache-control"] == "private, no-store"
    body = checked.json()
    assert body["status"] == "prechecked_quarantined"
    assert body["antivirus_status"] == "not_scanned"
    assert body["processing_allowed"] is False
    assert body["quarantine_active"] is True
    assert body["reason_code"] is None
    with Session(pg_engine) as db:
        attachment = db.get(MedicalAttachment, state["attachment"])
        review = db.scalar(select(AttachmentSecurityReview))
        assert attachment.extraction_status == "quarantined"
        assert attachment.extracted_text_ref is None
        assert review.checked_sha256 == attachment.content_sha256
        assert db.scalar(select(func.count(AttachmentSecurityEvent.id))) == 2
        assert db.scalar(select(func.count(AttachmentSecurityReview.id))) == 1
        assert ContextBuilder(db).build(state["patient"]).items == []
        assert ContextBuilder(db).build(state["patient"]).excluded_attachments_count == 1
        with pytest.raises(PermissionError):
            require_processing_clearance(attachment, review)


def test_roles_attachment_isolation_and_soft_delete(security_case, pg_engine):
    client, state, _, _ = security_case
    url = _url(state)
    state["active"] = state["doctor"]
    assert client.get(url).status_code == 200
    assert client.post(url + "/precheck").status_code == 403
    state["active"] = state["patient_user"]
    assert client.get(url).status_code == 403
    assert client.post(url + "/precheck").status_code == 403
    state["active"] = state["stranger"]
    assert client.get(url).status_code == 404
    # POST отклоняется на уровне admin-only роли до проверки доступа к пациенту.
    assert client.post(url + "/precheck").status_code == 403
    state["active"] = state["admin"]
    wrong = url.replace(state["attachment"], state["other_attachment"])
    assert client.get(wrong).status_code == 404
    assert client.post(wrong + "/precheck").status_code == 404
    with Session(pg_engine) as db:
        patient = db.get(Patient, state["patient"])
        patient.deleted_at = utc_now()
        db.commit()
    assert client.get(url).status_code == 404
    assert client.post(url + "/precheck").status_code == 404


def test_revoked_doctor_link_and_rejected_file_stays_rejected(security_case, pg_engine):
    client, state, store, payload = security_case
    url = _url(state)
    path = store.path_for_download(state["storage_key"])
    altered_payload = payload.replace(b"SYNTHETIC", b"MALICIOUS", 1)
    assert altered_payload != payload
    assert len(altered_payload) == len(payload)
    path.write_bytes(altered_payload)
    response = client.post(url + "/precheck")
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["reason_code"] == "hash_mismatch"
    path.write_bytes(payload)
    repeated = client.post(url + "/precheck")
    assert repeated.json()["status"] == "rejected"
    assert repeated.json()["reason_code"] == "hash_mismatch"
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count(AttachmentSecurityReview.id))) == 1
        assert db.scalar(select(func.count(AttachmentSecurityEvent.id))) == 2
        db.query(DoctorPatient).filter_by(id=state["link"]).delete()
        db.commit()
    state["active"] = state["doctor"]
    assert client.get(url).status_code == 404


def test_prechecked_file_tampered_again_is_rejected(security_case, pg_engine):
    client, state, store, _ = security_case
    url = _url(state)
    assert client.post(url + "/precheck").json()["status"] == "prechecked_quarantined"
    store.path_for_download(state["storage_key"]).write_bytes(b"changed")
    assert client.post(url + "/precheck").json()["status"] == "rejected"
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count(AttachmentSecurityReview.id))) == 1


def test_io_failure_records_error_but_remains_quarantined(
    security_case, pg_engine, monkeypatch
):
    client, state, _, _ = security_case
    import app.services.attachment_security as security_module

    def offline(*_args):
        raise InspectionUnavailable("Хранилище временно недоступно")

    monkeypatch.setattr(security_module, "_read_quarantined_file", offline)
    url = _url(state)
    response = client.post(url + "/precheck")
    assert response.status_code == 503
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count(AttachmentSecurityReview.id))) == 0
        event = db.scalar(select(AttachmentSecurityEvent))
        assert event.outcome == "error"
    assert client.get(url).json()["status"] == "quarantined"


def test_postgres_forbids_forged_release(security_case, pg_engine):
    _, state, _, _ = security_case
    with Session(pg_engine) as db:
        db.add(
            AttachmentSecurityReview(
                patient_id=state["patient"],
                attachment_id=state["attachment"],
                checked_by_id=state["admin"],
                status="released",
                checked_sha256="a" * 64,
                checked_length=10,
                reason_code=None,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_two_parallel_prechecks_single_review(security_case, pg_engine):
    _, state, store, _ = security_case
    barrier = Barrier(2)

    def run(_):
        with Session(pg_engine) as db:
            barrier.wait(timeout=10)
            attachment = db.scalar(
                select(MedicalAttachment)
                .where(MedicalAttachment.id == state["attachment"])
                .with_for_update()
            )
            return perform_precheck(
                db, attachment=attachment, actor_id=state["admin"], storage=store
            ).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert results == ["prechecked_quarantined", "prechecked_quarantined"]
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count(AttachmentSecurityReview.id))) == 1
        assert db.scalar(select(func.count(AttachmentSecurityEvent.id))) == 2


def test_missing_file_is_rejected(security_case):
    client, state, store, _ = security_case
    store.delete(state["storage_key"])
    result = client.post(_url(state) + "/precheck")
    assert result.status_code == 200
    assert result.json()["reason_code"] == "storage_missing"


def test_unauthenticated_security_routes():
    with TestClient(create_app()) as client:
        url = "/api/v1/patients/unknown/attachments/unknown/security"
        assert client.get(url).status_code == 401
        assert client.post(url + "/precheck").status_code == 401


def test_wrong_extraction_state_or_text_ref_refuses_precheck(security_case, pg_engine):
    client, state, _, _ = security_case
    url = _url(state)
    with Session(pg_engine) as db:
        attachment = db.get(MedicalAttachment, state["attachment"])
        attachment.extraction_status = "complete"
        db.commit()
    assert client.post(url + "/precheck").status_code == 409
    with Session(pg_engine) as db:
        attachment = db.get(MedicalAttachment, state["attachment"])
        attachment.extraction_status = "quarantined"
        attachment.extracted_text_ref = "unsafe-ref"
        db.commit()
    assert client.post(url + "/precheck").status_code == 409
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count(AttachmentSecurityReview.id))) == 0
        assert db.scalar(select(func.count(AttachmentSecurityEvent.id))) == 0


def test_audit_failure_prevents_successful_response(security_case, pg_engine):
    client, state, _, _ = security_case
    from sqlalchemy import event

    def deny_audit(_connection, _cursor, statement, _parameters, _context, _many):
        if "INSERT INTO attachment_security_events" in statement:
            raise RuntimeError("audit insert failed")

    event.listen(pg_engine, "before_cursor_execute", deny_audit)
    try:
        with pytest.raises(RuntimeError, match="audit insert failed"):
            client.get(_url(state))
        with pytest.raises(RuntimeError, match="audit insert failed"):
            client.post(_url(state) + "/precheck")
    finally:
        event.remove(pg_engine, "before_cursor_execute", deny_audit)

    with Session(pg_engine) as db:
        assert db.scalar(select(func.count(AttachmentSecurityReview.id))) == 0
        assert db.scalar(select(func.count(AttachmentSecurityEvent.id))) == 0
