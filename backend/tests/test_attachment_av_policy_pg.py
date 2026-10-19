"""6.3.3: PostgreSQL-аудит preflight-гейта и запрет клинического допуска."""

from datetime import UTC

import pytest
from app.models.attachment_av_scan import AttachmentAVScan
from app.models.attachment_security import AttachmentSecurityEvent, AttachmentSecurityReview
from app.models.medical_record import MedicalAttachment
from app.services.attachment_av_policy import PreflightGatedScanner
from app.services.attachment_av_scan import scan_quarantined_attachment
from app.services.attachment_clamd import ClamdVerdict
from app.services.attachment_scan_boundary import ScanAccessDenied
from app.services.attachment_security import ProcessingProhibited, require_processing_clearance
from app.services.clamd_health import eicar_bytes
from app.services.context_builder import ContextBuilder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.tests.test_attachment_scan_boundary_pg import scan_case as scan_case

VERSION = "ClamAV 1.5.4/28400/Mon Oct 19 11:00:00 2026"


class SimulatedClamd:
    def __init__(self, medical_status="clean_reported", *, eicar_ok=True):
        self.medical_status = medical_status
        self.eicar_ok = eicar_ok
        self.seen = []

    def scan(self, payload):
        self.seen.append(payload)
        if payload == eicar_bytes():
            status = "infected_reported" if self.eicar_ok else "clean_reported"
        else:
            status = self.medical_status
        return ClamdVerdict(status, VERSION)


def _scan(pg_engine, state, storage, fake, *, actor=None):
    from datetime import datetime

    scanner = PreflightGatedScanner(
        fake,
        clock=lambda: datetime(2026, 10, 19, 12, tzinfo=UTC),
    )
    with Session(pg_engine) as db:
        return scan_quarantined_attachment(
            db,
            patient_id=state["patient"],
            attachment_id=state["attachment"],
            actor_id=actor or state["admin"],
            storage=storage,
            scanner=scanner,
        )


def test_preflight_clean_report_is_still_quarantined_and_audited(scan_case, pg_engine):
    state, storage, payload = scan_case
    fake = SimulatedClamd()
    receipt = _scan(pg_engine, state, storage, fake)
    assert receipt.status == "clean_reported"
    assert fake.seen == [eicar_bytes(), payload, eicar_bytes()]
    with Session(pg_engine) as db:
        assert db.scalar(select(AttachmentAVScan)).status == "clean_reported"
        assert db.scalar(select(AttachmentSecurityReview)).status == "prechecked_quarantined"
        attachment = db.get(MedicalAttachment, state["attachment"])
        assert attachment.extraction_status == "quarantined"
        assert attachment.extracted_text_ref is None
        with pytest.raises(ProcessingProhibited):
            require_processing_clearance(attachment, db.scalar(select(AttachmentSecurityReview)))
        assert ContextBuilder(db).build(state["patient"]).items == []
        assert db.scalar(
            select(func.count()).select_from(AttachmentSecurityEvent).where(
                AttachmentSecurityEvent.action == "av_scan",
            )
        ) == 1


def test_failed_eicar_records_error_and_never_transfers_medical_bytes(scan_case, pg_engine):
    state, storage, _ = scan_case
    fake = SimulatedClamd(eicar_ok=False)
    receipt = _scan(pg_engine, state, storage, fake)
    assert receipt.status == "error"
    assert receipt.reason_code == "scanner_unavailable"
    assert fake.seen == [eicar_bytes()]
    with Session(pg_engine) as db:
        assert db.scalar(select(AttachmentAVScan)).status == "error"
        assert db.scalar(select(AttachmentSecurityReview)).status == "prechecked_quarantined"
        assert db.scalar(
            select(func.count()).select_from(AttachmentSecurityEvent).where(
                AttachmentSecurityEvent.action == "av_scan",
                AttachmentSecurityEvent.outcome == "error",
            )
        ) == 1


def test_detected_file_rejected_without_postflight(scan_case, pg_engine):
    state, storage, payload = scan_case
    fake = SimulatedClamd(medical_status="infected_reported")
    receipt = _scan(pg_engine, state, storage, fake)
    assert receipt.status == "infected_reported"
    assert fake.seen == [eicar_bytes(), payload]
    with Session(pg_engine) as db:
        review = db.scalar(select(AttachmentSecurityReview))
        assert review.status == "rejected"
        assert review.reason_code == "av_detected"


def test_role_denied_before_preflight(scan_case, pg_engine):
    state, storage, _ = scan_case
    fake = SimulatedClamd()
    with pytest.raises(ScanAccessDenied):
        _scan(pg_engine, state, storage, fake, actor=state["doctor"])
    assert fake.seen == []
    with Session(pg_engine) as db:
        assert db.scalar(select(func.count()).select_from(AttachmentAVScan)) == 0
