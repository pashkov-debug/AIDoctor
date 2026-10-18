"""6.3.1: PostgreSQL-интеграция на синтетических AV-ответах, НЕ реальный clamd."""

import pytest
from app.models.attachment_av_scan import AttachmentAVScan
from app.models.attachment_security import AttachmentSecurityEvent, AttachmentSecurityReview
from app.models.medical_record import MedicalAttachment
from app.services.attachment_av_scan import scan_quarantined_attachment
from app.services.attachment_clamd import ClamdUnavailable, ClamdVerdict
from app.services.attachment_scan_boundary import ScanAccessDenied
from app.services.attachment_security import ProcessingProhibited, require_processing_clearance
from app.services.context_builder import ContextBuilder
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from backend.tests.test_attachment_scan_boundary_pg import scan_case as scan_case


class SimulatedClamd:
    def __init__(self, *, status="clean_reported", storage=None, key=None):
        self.status = status
        self.storage = storage
        self.key = key
        self.calls = 0

    def scan(self, payload):
        assert payload.startswith(b"%PDF-")
        self.calls += 1
        if self.storage:
            self.storage.path_for_download(self.key).write_bytes(payload + b"changed")
        if self.status == "offline":
            raise ClamdUnavailable("local daemon unavailable")
        return ClamdVerdict(self.status, "ClamAV synthetic-test")


def _run(engine, state, storage, scanner=None, **override):
    args = {
        "patient_id": state["patient"],
        "attachment_id": state["attachment"],
        "actor_id": state["admin"],
        "storage": storage,
        "scanner": scanner or SimulatedClamd(),
    }
    args.update(override)
    with Session(engine) as db:
        return scan_quarantined_attachment(db, **args)


def test_clean_response_remains_quarantined_and_does_not_enter_context(scan_case, pg_engine):
    state, storage, payload = scan_case
    scanner = SimulatedClamd()
    result = _run(pg_engine, state, storage, scanner)
    assert result.status == "clean_reported"
    assert result.content_sha256
    assert result.content_length == len(payload)
    assert scanner.calls == 1
    with Session(pg_engine) as db:
        attachment = db.get(MedicalAttachment, state["attachment"])
        review = db.scalar(select(AttachmentSecurityReview))
        assert review.status == "prechecked_quarantined"
        assert attachment.extraction_status == "quarantined"
        assert attachment.extracted_text_ref is None
        assert ContextBuilder(db).build(state["patient"]).items == []
        with pytest.raises(ProcessingProhibited):
            require_processing_clearance(attachment, review)
        actions = db.scalars(select(AttachmentSecurityEvent.action)).all()
        assert actions.count("scan_input") == 1
        assert actions.count("av_scan") == 1


def test_infection_report_is_terminal_rejection(scan_case, pg_engine):
    state, storage, _ = scan_case
    result = _run(pg_engine, state, storage, SimulatedClamd(status="infected_reported"))
    assert result.status == "infected_reported"
    with Session(pg_engine) as db:
        review = db.scalar(select(AttachmentSecurityReview))
        assert review.status == "rejected"
        assert review.reason_code == "av_detected"
    with pytest.raises(ProcessingProhibited):
        _run(pg_engine, state, storage)


def test_clamd_failure_records_error_and_preserves_quarantine(scan_case, pg_engine):
    state, storage, _ = scan_case
    result = _run(pg_engine, state, storage, SimulatedClamd(status="offline"))
    assert result.status == "error"
    assert result.reason_code == "scanner_unavailable"
    assert result.engine_version is None
    with Session(pg_engine) as db:
        assert db.scalar(select(AttachmentSecurityReview)).status == "prechecked_quarantined"


def test_postscan_tampering_prevents_success_and_rejects(scan_case, pg_engine):
    state, storage, _ = scan_case
    tampering = SimulatedClamd(storage=storage, key=state["key"])
    result = _run(pg_engine, state, storage, tampering)
    assert result.status == "error"
    assert result.reason_code == "postscan_file_changed"
    with Session(pg_engine) as db:
        assert db.scalar(select(AttachmentSecurityReview)).status == "rejected"


def test_access_denied_before_scanner(scan_case, pg_engine):
    state, storage, _ = scan_case
    scanner = SimulatedClamd()
    with pytest.raises(ScanAccessDenied):
        _run(pg_engine, state, storage, scanner, actor_id=state["doctor"])
    assert scanner.calls == 0
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count()).select_from(AttachmentAVScan)) == 0


def test_invalid_verdict_fail_closed(scan_case, pg_engine):
    state, storage, _ = scan_case
    report = _run(pg_engine, state, storage, SimulatedClamd(status="unexpected"))
    assert report.status == "error"
    assert report.reason_code == "invalid_scanner_verdict"


def test_audit_failure_rolls_back_report(scan_case, pg_engine):
    state, storage, _ = scan_case

    def fail_audit(_conn, _cursor, statement, _params, _ctx, _many):
        if "INSERT INTO attachment_security_events" in statement:
            # capture тоже пишет аудит, но он должен пройти прежде чем scan начнётся;
            # блокируем только после успешной записи capture с помощью счётчика.
            fail_audit.count += 1
            if fail_audit.count > 1:
                raise RuntimeError("audit unavailable")

    fail_audit.count = 0
    event.listen(pg_engine, "before_cursor_execute", fail_audit)
    try:
        with pytest.raises(RuntimeError, match="audit unavailable"):
            _run(pg_engine, state, storage)
    finally:
        event.remove(pg_engine, "before_cursor_execute", fail_audit)
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count()).select_from(AttachmentAVScan)) == 0
        assert db.scalar(select(func.count()).select_from(AttachmentSecurityEvent).where(
            AttachmentSecurityEvent.action == "scan_input"
        )) == 1


def test_role_revocation_during_scan_never_saves_clean(scan_case, pg_engine):
    state, storage, _ = scan_case

    class RevokingScanner(SimulatedClamd):
        def scan(self, payload):
            from app.models.access import User

            with Session(pg_engine) as db:
                db.get(User, state["admin"]).role = "doctor"
                db.commit()
            return super().scan(payload)

    result = _run(pg_engine, state, storage, RevokingScanner())
    assert result.status == "error"
    assert result.reason_code == "state_changed"


def test_wrong_daemon_version_never_saves_clean(scan_case, pg_engine):
    state, storage, _ = scan_case

    class BadVersionScanner(SimulatedClamd):
        def scan(self, payload):
            super().scan(payload)
            return ClamdVerdict("clean_reported", "untrusted protocol")

    result = _run(pg_engine, state, storage, BadVersionScanner())
    assert result.status == "error"
    assert result.reason_code == "invalid_scanner_version"
    with Session(pg_engine) as db:
        assert db.scalar(select(AttachmentSecurityReview)).status == "prechecked_quarantined"
