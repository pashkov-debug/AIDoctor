"""6.6 FINAL: сквозная PostgreSQL-регрессия карантина и отказов AV.

Только TEST_DATABASE_URL на локальную базу *_test (проверяет conftest.py).
Сканеры здесь синтетические; реальный ClamAV тестируется отдельной CLI.
"""

import pytest
from app.models.attachment_av_scan import AttachmentAVScan
from app.models.attachment_security import AttachmentSecurityEvent, AttachmentSecurityReview
from app.models.medical_record import MedicalAttachment
from app.services.attachment_av_scan import scan_quarantined_attachment
from app.services.attachment_cdr_boundary import prepare_quarantined_cdr_candidate
from app.services.attachment_security import ProcessingProhibited, require_processing_clearance
from app.services.context_builder import ContextBuilder
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.tests.test_attachment_scan_boundary_pg import scan_case as scan_case


class FailingScanner:
    def __init__(self, *, response=None, failure=None):
        self.calls = 0
        self.response = response
        self.failure = failure

    def scan(self, _payload):
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.response


@pytest.mark.parametrize(
    ("failure", "response"),
    [
        (RuntimeError("confidential scanner failure"), None),
        (ValueError("confidential invalid scanner payload"), None),
        (TimeoutError("scanner timeout"), None),
        (None, None),
        (None, object()),
    ],
    ids=["runtime-error", "value-error", "timeout", "none", "malformed"],
)
def test_unexpected_av_failure_is_audited_without_releasing(
    scan_case, pg_engine, failure, response
):
    state, storage, _ = scan_case
    scanner = FailingScanner(response=response, failure=failure)
    with Session(pg_engine) as db:
        receipt = scan_quarantined_attachment(
            db,
            patient_id=state["patient"],
            attachment_id=state["attachment"],
            actor_id=state["admin"],
            storage=storage,
            scanner=scanner,
        )
    assert scanner.calls == 1
    assert receipt.status == "error"
    assert receipt.reason_code == "scanner_unavailable"
    assert receipt.engine_version is None

    with Session(pg_engine) as db:
        attachment = db.get(MedicalAttachment, state["attachment"])
        review = db.scalar(select(AttachmentSecurityReview))
        assert attachment.extraction_status == "quarantined"
        assert attachment.extracted_text_ref is None
        assert review.status == "prechecked_quarantined"
        assert db.scalar(select(func.count()).select_from(AttachmentAVScan)) == 1
        events = db.scalars(
            select(AttachmentSecurityEvent)
            .where(AttachmentSecurityEvent.action == "av_scan")
        ).all()
        assert len(events) == 1
        assert events[0].outcome == "error"
        assert events[0].reason_code == "scanner_unavailable"
        assert ContextBuilder(db).build(state["patient"]).items == []
        with pytest.raises(ProcessingProhibited):
            require_processing_clearance(attachment, review)
        # Ошибка AV не должна допускать даже выдачу кандидата для CDR.
        with pytest.raises(ProcessingProhibited):
            prepare_quarantined_cdr_candidate(
                db,
                patient_id=state["patient"],
                attachment_id=state["attachment"],
                actor_id=state["admin"],
                storage=storage,
            )


def test_successful_av_report_still_cannot_clear_clinical_gate(scan_case, pg_engine):
    from app.services.attachment_clamd import ClamdVerdict

    state, storage, _ = scan_case
    fake = FailingScanner(response=ClamdVerdict(
        "clean_reported", "ClamAV 1.5.4/12345/Sun Oct 18 06:24:14 2026"
    ))
    with Session(pg_engine) as db:
        receipt = scan_quarantined_attachment(
            db,
            patient_id=state["patient"],
            attachment_id=state["attachment"],
            actor_id=state["admin"],
            storage=storage,
            scanner=fake,
        )
    assert receipt.status == "clean_reported"
    with Session(pg_engine) as db:
        attachment = db.get(MedicalAttachment, state["attachment"])
        review = db.scalar(select(AttachmentSecurityReview))
        assert attachment.extraction_status == "quarantined"
        assert review.status == "prechecked_quarantined"
        assert ContextBuilder(db).build(state["patient"]).items == []
        with pytest.raises(ProcessingProhibited):
            require_processing_clearance(attachment, review)
