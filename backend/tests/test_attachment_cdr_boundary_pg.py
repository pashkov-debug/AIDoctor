"""6.4.0: PostgreSQL-проверки границы CDR на синтетических вложениях.

Отчёт AV в фикстуре СИНТЕТИЧЕСКИЙ: тестирует отбор по БД,
не является тестом настоящего ClamAV или CDR-движка.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from app.db.base import utc_now
from app.models.attachment_av_scan import AttachmentAVScan
from app.models.attachment_security import AttachmentSecurityEvent, AttachmentSecurityReview
from app.models.medical_record import MedicalAttachment
from app.models.patient import Patient
from app.services.attachment_cdr_boundary import (
    CDRAccessDenied,
    prepare_quarantined_cdr_candidate,
)
from app.services.attachment_security import (
    InspectionUnavailable,
    ProcessingProhibited,
    require_processing_clearance,
)
from app.services.context_builder import ContextBuilder
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from backend.tests.test_attachment_scan_boundary_pg import scan_case as scan_case


@pytest.fixture
def cdr_case(scan_case, pg_engine):
    state, storage, payload = scan_case
    with Session(pg_engine) as db:
        report = AttachmentAVScan(
            actor_id=state["admin"],
            patient_id=state["patient"],
            attachment_id=state["attachment"],
            content_sha256=db.get(MedicalAttachment, state["attachment"]).content_sha256,
            content_length=len(payload),
            status="clean_reported",
            reason_code=None,
            engine_name="clamd",
            engine_version="ClamAV synthetic-test-report",
        )
        db.add(report)
        db.commit()
        report_id = report.id
    return state, storage, payload, report_id


def _candidate(engine, state, storage, **overrides):
    kwargs = dict(
        patient_id=state["patient"], attachment_id=state["attachment"],
        actor_id=state["admin"], storage=storage,
    )
    kwargs.update(overrides)
    with Session(engine) as db:
        return prepare_quarantined_cdr_candidate(db, **kwargs)


def _events(engine):
    with Session(engine) as db:
        return db.scalars(
            select(AttachmentSecurityEvent)
            .where(AttachmentSecurityEvent.action == "cdr_input")
        ).all()


def test_cdr_candidate_is_not_a_sanitized_file_or_clinical_fact(cdr_case, pg_engine):
    state, storage, payload, report_id = cdr_case
    candidate = _candidate(pg_engine, state, storage)
    assert candidate.content == payload
    assert candidate.av_report_id == report_id
    assert candidate.processing_allowed is False
    assert candidate.source_sha256
    assert "SYNTHETIC" not in repr(candidate)
    with Session(pg_engine) as db:
        attachment = db.get(MedicalAttachment, state["attachment"])
        review = db.scalar(select(AttachmentSecurityReview))
        assert attachment.extraction_status == "quarantined"
        assert attachment.extracted_text_ref is None
        assert review.status == "prechecked_quarantined"
        assert ContextBuilder(db).build(state["patient"]).items == []
        with pytest.raises(ProcessingProhibited):
            require_processing_clearance(attachment, review)
    events = _events(pg_engine)
    assert len(events) == 1
    assert events[0].outcome == "prechecked_quarantined"
    assert events[0].reason_code is None


def test_no_av_report_blocks_without_file_read(scan_case, pg_engine, monkeypatch):
    state, storage, _ = scan_case
    import app.services.attachment_cdr_boundary as cdr_module

    def must_not_read(*_args, **_kwargs):
        raise AssertionError("Нельзя читать файл без AV-отчёта")

    monkeypatch.setattr(cdr_module, "_read_quarantined_file", must_not_read)
    with pytest.raises(ProcessingProhibited):
        _candidate(pg_engine, state, storage)
    events = _events(pg_engine)
    assert len(events) == 1
    assert events[0].reason_code == "av_report_missing"


def test_latest_failed_report_supersedes_old_clean(cdr_case, pg_engine):
    state, storage, _, _ = cdr_case
    with Session(pg_engine) as db:
        old = db.scalar(select(AttachmentAVScan))
        db.add(AttachmentAVScan(
            actor_id=state["admin"], patient_id=state["patient"],
            attachment_id=state["attachment"],
            content_sha256=old.content_sha256, content_length=old.content_length,
            status="error", reason_code="scanner_unavailable",
            engine_name="clamd", engine_version=None,
            created_at=old.created_at + timedelta(seconds=1),
        ))
        db.commit()
    with pytest.raises(ProcessingProhibited):
        _candidate(pg_engine, state, storage)
    assert _events(pg_engine)[0].reason_code == "av_not_clean"


def test_expired_report_is_not_a_candidate(cdr_case, pg_engine, monkeypatch):
    state, storage, _, _ = cdr_case
    import app.services.attachment_cdr_boundary as cdr_module

    simulated_future = utc_now() + timedelta(days=2)
    monkeypatch.setattr(cdr_module, "utc_now", lambda: simulated_future)
    with pytest.raises(ProcessingProhibited):
        _candidate(pg_engine, state, storage)
    assert _events(pg_engine)[0].reason_code == "av_report_stale"


def test_only_admin_with_active_patient_can_capture(cdr_case, pg_engine):
    state, storage, _, _ = cdr_case
    with pytest.raises(CDRAccessDenied):
        _candidate(pg_engine, state, storage, actor_id=state["doctor"])
    with pytest.raises(CDRAccessDenied):
        _candidate(pg_engine, state, storage, patient_id="missing-patient")
    with pytest.raises(CDRAccessDenied):
        _candidate(pg_engine, state, storage, attachment_id="missing-attachment")
    with Session(pg_engine) as db:
        db.get(Patient, state["patient"]).deleted_at = utc_now()
        db.commit()
    with pytest.raises(CDRAccessDenied):
        _candidate(pg_engine, state, storage)
    assert _events(pg_engine) == []


def test_tamper_after_clean_report_terminals_rejection(cdr_case, pg_engine):
    state, storage, payload, _ = cdr_case
    modified = payload.replace(b"SYNTHETIC", b"MALICIOUS")
    assert len(modified) == len(payload)
    storage.path_for_download(state["key"]).write_bytes(modified)
    with pytest.raises(ProcessingProhibited):
        _candidate(pg_engine, state, storage)
    with Session(pg_engine) as db:
        review = db.scalar(select(AttachmentSecurityReview))
        assert review.status == "rejected"
        assert review.reason_code == "hash_mismatch"
    assert _events(pg_engine)[0].outcome == "rejected"
    storage.path_for_download(state["key"]).write_bytes(payload)
    with pytest.raises(ProcessingProhibited):
        _candidate(pg_engine, state, storage)
    assert _events(pg_engine)[1].reason_code == "precheck_not_ready"


def test_io_failure_is_audited_and_quarantine_remains(cdr_case, pg_engine, monkeypatch):
    state, storage, _, _ = cdr_case
    import app.services.attachment_cdr_boundary as cdr_module

    def unavailable(*_args, **_kwargs):
        raise InspectionUnavailable("storage unavailable")

    monkeypatch.setattr(cdr_module, "_read_quarantined_file", unavailable)
    with pytest.raises(InspectionUnavailable):
        _candidate(pg_engine, state, storage)
    assert _events(pg_engine)[0].reason_code == "storage_unavailable"
    with Session(pg_engine) as db:
        assert db.scalar(select(AttachmentSecurityReview)).status == "prechecked_quarantined"


def test_failed_audit_prevents_cdr_bytes_return(cdr_case, pg_engine):
    state, storage, _, _ = cdr_case

    def fail_audit(_conn, _cursor, statement, _params, _ctx, _many):
        if "INSERT INTO attachment_security_events" in statement:
            raise RuntimeError("audit unavailable")

    event.listen(pg_engine, "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            _candidate(pg_engine, state, storage)
    finally:
        event.remove(pg_engine, "before_cursor_execute", fail_audit)
    assert _events(pg_engine) == []


def test_two_parallel_requests_have_two_committed_audits(cdr_case, pg_engine):
    state, storage, payload, _ = cdr_case
    barrier = Barrier(2)

    def one_request(_index):
        barrier.wait(timeout=10)
        return _candidate(pg_engine, state, storage).content

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(one_request, range(2))) == [payload, payload]
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count()).select_from(
            AttachmentSecurityEvent
        ).where(AttachmentSecurityEvent.action == "cdr_input")) == 2


def test_changes_to_extraction_state_block_candidate(cdr_case, pg_engine):
    state, storage, _, _ = cdr_case
    with Session(pg_engine) as db:
        db.get(MedicalAttachment, state["attachment"]).extracted_text_ref = "unsafe"
        db.commit()
    with pytest.raises(ProcessingProhibited):
        _candidate(pg_engine, state, storage)
    assert _events(pg_engine)[0].reason_code == "invalid_extraction_state"


def test_rejection_and_audit_rollback_atomically(cdr_case, pg_engine):
    state, storage, payload, _ = cdr_case
    storage.path_for_download(state["key"]).write_bytes(payload + b"append")

    def fail_audit(_conn, _cursor, statement, _params, _ctx, _many):
        if "INSERT INTO attachment_security_events" in statement:
            raise RuntimeError("audit unavailable")

    event.listen(pg_engine, "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            _candidate(pg_engine, state, storage)
    finally:
        event.remove(pg_engine, "before_cursor_execute", fail_audit)
    with Session(pg_engine) as db:
        assert db.scalar(select(AttachmentSecurityReview)).status == "prechecked_quarantined"
        assert db.scalar(select(func.count()).select_from(AttachmentSecurityEvent).where(
            AttachmentSecurityEvent.action == "cdr_input"
        )) == 0
