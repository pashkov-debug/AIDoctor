"""6.3.0: проверяем границу AV-входа на изолированной БД PostgreSQL *_test."""

import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from app.db.base import utc_now
from app.models.access import User
from app.models.attachment_security import AttachmentSecurityEvent, AttachmentSecurityReview
from app.models.medical_record import MedicalAttachment
from app.models.patient import Patient
from app.services.attachment_scan_boundary import (
    ScanAccessDenied,
    capture_quarantined_scan_input,
)
from app.services.attachment_security import (
    InspectionUnavailable,
    ProcessingProhibited,
    perform_precheck,
    require_processing_clearance,
)
from app.services.attachment_storage import AttachmentStorage
from app.services.context_builder import ContextBuilder
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@pytest.fixture
def scan_case(pg_engine, tmp_path):
    storage = AttachmentStorage(tmp_path)
    payload = b"%PDF-1.7\\nSYNTHETIC-STAGE-6.3"
    saved = storage.save(io.BytesIO(payload), "isolation.pdf")
    with Session(pg_engine) as db:
        admin = User(username="scan-admin", password_hash="synthetic", role="admin")
        doctor = User(username="scan-doctor", password_hash="synthetic", role="doctor")
        patient = Patient(alias="SCAN-SYNTHETIC", demographics_json={})
        db.add_all([admin, doctor, patient])
        db.flush()
        attachment = MedicalAttachment(
            patient_id=patient.id,
            uploaded_by_id=admin.id,
            filename=saved.filename,
            media_type=saved.media_type,
            content_sha256=saved.content_sha256,
            content_length=saved.content_length,
            storage_key=saved.key,
            extraction_status="quarantined",
        )
        db.add(attachment)
        db.flush()
        state = {
            "admin": admin.id,
            "doctor": doctor.id,
            "patient": patient.id,
            "attachment": attachment.id,
            "key": saved.key,
        }
        db.commit()

    with Session(pg_engine) as db:
        attachment = db.scalar(
            select(MedicalAttachment)
            .where(MedicalAttachment.id == state["attachment"])
            .with_for_update()
        )
        review = perform_precheck(
            db, attachment=attachment, actor_id=state["admin"], storage=storage
        )
        assert review.status == "prechecked_quarantined"
    return state, storage, payload


def _capture(engine, state, storage, **overrides):
    args = {
        "patient_id": state["patient"],
        "attachment_id": state["attachment"],
        "actor_id": state["admin"],
        "storage": storage,
    }
    args.update(overrides)
    with Session(engine) as db:
        return capture_quarantined_scan_input(db, **args)


def test_verified_snapshot_is_immutable_and_does_not_release(scan_case, pg_engine):
    state, storage, payload = scan_case
    result = _capture(pg_engine, state, storage)
    assert result.content == payload
    assert result.content_length == len(payload)
    assert result.patient_id == state["patient"]
    assert result.attachment_id == state["attachment"]

    storage.path_for_download(state["key"]).write_bytes(b"changed-after-capture")
    assert result.content == payload  # Нет повторного чтения файла по пути.
    with Session(pg_engine) as db:
        attachment = db.get(MedicalAttachment, state["attachment"])
        review = db.scalar(select(AttachmentSecurityReview))
        assert review.status == "prechecked_quarantined"
        assert attachment.extraction_status == "quarantined"
        assert attachment.extracted_text_ref is None
        assert ContextBuilder(db).build(state["patient"]).items == []
        assert ContextBuilder(db).build(state["patient"]).excluded_attachments_count == 1
        with pytest.raises(ProcessingProhibited):
            require_processing_clearance(attachment, review)
        assert (
            db.scalar(
                select(func.count())
                .select_from(AttachmentSecurityEvent)
                .where(
                    AttachmentSecurityEvent.action == "scan_input",
                    AttachmentSecurityEvent.outcome == "prechecked_quarantined",
                )
            )
            == 1
        )


def test_admin_only_and_patient_isolation(scan_case, pg_engine):
    state, storage, _ = scan_case
    with pytest.raises(ScanAccessDenied):
        _capture(pg_engine, state, storage, actor_id=state["doctor"])
    with pytest.raises(ScanAccessDenied):
        _capture(pg_engine, state, storage, patient_id="missing-patient")
    with pytest.raises(ScanAccessDenied):
        _capture(pg_engine, state, storage, attachment_id="missing-attachment")
    with Session(pg_engine) as db:
        other = Patient(alias="DIFFERENT-PATIENT", demographics_json={})
        db.add(other)
        db.commit()
        different_patient = other.id
    with pytest.raises(ScanAccessDenied):
        _capture(pg_engine, state, storage, patient_id=different_patient)
    with Session(pg_engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AttachmentSecurityEvent)
                .where(AttachmentSecurityEvent.action == "scan_input")
            )
            == 0
        )
        db.get(Patient, state["patient"]).deleted_at = utc_now()
        db.commit()
    with pytest.raises(ScanAccessDenied):
        _capture(pg_engine, state, storage)


def test_tampered_prechecked_file_terminally_rejected(scan_case, pg_engine):
    state, storage, payload = scan_case
    replacement = payload.replace(b"SYNTHETIC", b"MALICIOUS", 1)
    assert len(replacement) == len(payload)
    storage.path_for_download(state["key"]).write_bytes(replacement)
    with pytest.raises(ProcessingProhibited):
        _capture(pg_engine, state, storage)
    with Session(pg_engine) as db:
        review = db.scalar(select(AttachmentSecurityReview))
        assert review.status == "rejected"
        assert review.reason_code == "hash_mismatch"
        events = db.scalars(
            select(AttachmentSecurityEvent).where(AttachmentSecurityEvent.action == "scan_input")
        ).all()
        assert len(events) == 1
        assert events[0].outcome == "rejected"
    storage.path_for_download(state["key"]).write_bytes(payload)
    with pytest.raises(ProcessingProhibited):
        _capture(pg_engine, state, storage)
    with Session(pg_engine) as db:
        assert db.scalar(select(AttachmentSecurityReview)).status == "rejected"


def test_precheck_required_and_extracted_ref_blocked(scan_case, pg_engine):
    state, storage, _ = scan_case
    with Session(pg_engine) as db:
        db.query(AttachmentSecurityReview).delete()
        db.commit()
    with pytest.raises(ProcessingProhibited):
        _capture(pg_engine, state, storage)
    with Session(pg_engine) as db:
        events = db.scalars(
            select(AttachmentSecurityEvent).where(AttachmentSecurityEvent.action == "scan_input")
        ).all()
        assert len(events) == 1
        assert events[0].outcome == "quarantined"


def test_changed_extraction_state_blocks_snapshot(scan_case, pg_engine):
    state, storage, _ = scan_case
    with Session(pg_engine) as db:
        db.get(MedicalAttachment, state["attachment"]).extracted_text_ref = "unsafe"
        db.commit()
    with pytest.raises(ProcessingProhibited):
        _capture(pg_engine, state, storage)


def test_scan_io_failure_fails_closed_with_audit(scan_case, pg_engine, monkeypatch):
    state, storage, _ = scan_case
    import app.services.attachment_scan_boundary as scan_module

    def broken(*_args, **_kwargs):
        raise InspectionUnavailable("storage offline")

    monkeypatch.setattr(scan_module, "_read_quarantined_file", broken)
    with pytest.raises(InspectionUnavailable):
        _capture(pg_engine, state, storage)
    with Session(pg_engine) as db:
        event_row = db.scalar(
            select(AttachmentSecurityEvent).where(AttachmentSecurityEvent.action == "scan_input")
        )
        assert event_row.outcome == "error"
        assert db.scalar(select(AttachmentSecurityReview)).status == "prechecked_quarantined"


def test_audit_insert_failure_prevents_returning_bytes(scan_case, pg_engine):
    state, storage, _ = scan_case

    def fail_audit(_conn, _cursor, statement, _params, _ctx, _many):
        if "INSERT INTO attachment_security_events" in statement:
            raise RuntimeError("audit unavailable")

    event.listen(pg_engine, "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            _capture(pg_engine, state, storage)
    finally:
        event.remove(pg_engine, "before_cursor_execute", fail_audit)


def test_parallel_scans_serialize_and_preserve_state(scan_case, pg_engine):
    state, storage, payload = scan_case
    barrier = Barrier(2)

    def capture_once(_index):
        barrier.wait(timeout=10)
        return _capture(pg_engine, state, storage).content

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(capture_once, range(2)))
    assert results == [payload, payload]
    with Session(pg_engine) as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(AttachmentSecurityEvent)
                .where(AttachmentSecurityEvent.action == "scan_input")
            )
            == 2
        )


def test_postgres_disallows_forged_scanner_result(scan_case, pg_engine):
    state, _, _ = scan_case
    with Session(pg_engine) as db:
        db.add(
            AttachmentSecurityEvent(
                actor_id=state["admin"],
                patient_id=state["patient"],
                attachment_id=state["attachment"],
                action="scan_passed",
                outcome="prechecked_quarantined",
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_missing_prechecked_file_becomes_terminally_rejected(scan_case, pg_engine):
    state, storage, _ = scan_case
    storage.delete(state["key"])
    with pytest.raises(ProcessingProhibited):
        _capture(pg_engine, state, storage)
    with Session(pg_engine) as db:
        review = db.scalar(select(AttachmentSecurityReview))
        assert review.status == "rejected"
        assert review.reason_code == "storage_missing"


def test_stale_precheck_fingerprint_does_not_release_bytes(scan_case, pg_engine):
    state, storage, _ = scan_case
    with Session(pg_engine) as db:
        db.scalar(select(AttachmentSecurityReview)).checked_sha256 = "0" * 64
        db.commit()
    with pytest.raises(ProcessingProhibited):
        _capture(pg_engine, state, storage)
    with Session(pg_engine) as db:
        event_row = db.scalar(
            select(AttachmentSecurityEvent).where(AttachmentSecurityEvent.action == "scan_input")
        )
        assert event_row.reason_code == "scan_input_not_ready"


def test_rejection_and_audit_atomic_on_database_failure(scan_case, pg_engine):
    state, storage, payload = scan_case
    storage.path_for_download(state["key"]).write_bytes(payload + b"modified")

    def fail_audit(_conn, _cursor, statement, _params, _ctx, _many):
        if "INSERT INTO attachment_security_events" in statement:
            raise RuntimeError("audit unavailable")

    event.listen(pg_engine, "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            _capture(pg_engine, state, storage)
    finally:
        event.remove(pg_engine, "before_cursor_execute", fail_audit)

    with Session(pg_engine) as db:
        # Откат транзакции возвращает старую запись, но выдачи байтов не было.
        assert db.scalar(select(AttachmentSecurityReview)).status == "prechecked_quarantined"
        assert (
            db.scalar(
                select(func.count())
                .select_from(AttachmentSecurityEvent)
                .where(AttachmentSecurityEvent.action == "scan_input")
            )
            == 0
        )
