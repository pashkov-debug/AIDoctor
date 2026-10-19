"""6.4.0: чистая политика CDR-кандидата, без запуска парсеров и CDR."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from app.services.attachment_cdr_boundary import (
    QuarantinedCDRCandidate,
    cdr_candidate_rejection_reason,
)

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
HASH = "b" * 64
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def make_objects(filename="source.pdf", media_type=PDF):
    attachment = SimpleNamespace(
        id="attachment", patient_id="patient", filename=filename,
        media_type=media_type, extraction_status="quarantined",
        extracted_text_ref=None, content_sha256=HASH, content_length=50,
    )
    review = SimpleNamespace(
        attachment_id="attachment", patient_id="patient",
        status="prechecked_quarantined", checked_sha256=HASH,
        checked_length=50, checked_at=NOW - timedelta(hours=2),
    )
    report = SimpleNamespace(
        id="report", attachment_id="attachment", patient_id="patient",
        content_sha256=HASH, content_length=50, status="clean_reported",
        reason_code=None, engine_name="clamd",
        engine_version="ClamAV 1.5.4/28400/Mon Oct 19 11:00:00 2026",
        created_at=NOW - timedelta(hours=1),
    )
    return attachment, review, report


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"filename": "source.doc"}, "unsupported_format"),
        ({"filename": "source.exe"}, "unsupported_format"),
        ({"media_type": "image/png"}, "unsupported_format"),
        ({"extraction_status": "extracted"}, "invalid_extraction_state"),
        ({"extracted_text_ref": "unsafe"}, "invalid_extraction_state"),
    ],
)
def test_source_policy_fails_closed(mutation, reason):
    attachment, review, report = make_objects()
    attachment.__dict__.update(mutation)
    assert cdr_candidate_rejection_reason(
        attachment, review, report, now=NOW
    ) == reason


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"status": "rejected"}, "precheck_not_ready"),
        ({"patient_id": "foreign"}, "precheck_not_ready"),
        ({"checked_sha256": "a" * 64}, "precheck_not_ready"),
        ({"checked_length": 51}, "precheck_not_ready"),
    ],
)
def test_precheck_policy_rejects_inconsistencies(mutation, reason):
    attachment, review, report = make_objects()
    review.__dict__.update(mutation)
    assert cdr_candidate_rejection_reason(
        attachment, review, report, now=NOW
    ) == reason


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ({"status": "infected_reported"}, "av_not_clean"),
        ({"status": "error"}, "av_not_clean"),
        ({"content_sha256": "0" * 64}, "av_report_mismatch"),
        ({"content_length": 49}, "av_report_mismatch"),
        ({"patient_id": "foreign"}, "av_report_mismatch"),
        ({"engine_name": "other"}, "av_report_mismatch"),
        ({"engine_version": ""}, "av_report_mismatch"),
        ({"reason_code": "bad"}, "av_report_mismatch"),
        ({"created_at": NOW - timedelta(days=2)}, "av_report_stale"),
        ({"created_at": NOW + timedelta(seconds=1)}, "av_report_stale"),
        ({"created_at": NOW - timedelta(hours=3)}, "av_report_stale"),
        ({"created_at": NOW.replace(tzinfo=None)}, "invalid_av_time"),
    ],
)
def test_av_report_policy_rejects_inconsistencies(mutation, reason):
    attachment, review, report = make_objects()
    report.__dict__.update(mutation)
    assert cdr_candidate_rejection_reason(
        attachment, review, report, now=NOW
    ) == reason


def test_missing_review_or_report_is_denied():
    attachment, review, report = make_objects()
    assert cdr_candidate_rejection_reason(
        attachment, None, report, now=NOW
    ) == "precheck_not_ready"
    assert cdr_candidate_rejection_reason(
        attachment, review, None, now=NOW
    ) == "av_report_missing"


@pytest.mark.parametrize(("filename", "media"), [("a.pdf", PDF), ("a.docx", DOCX)])
def test_supported_type_is_only_candidate_not_clearance(filename, media):
    attachment, review, report = make_objects(filename, media)
    assert cdr_candidate_rejection_reason(
        attachment, review, report, now=NOW
    ) is None


def test_candidate_is_immutable_hides_payload_and_prohibits_processing():
    item = QuarantinedCDRCandidate(
        patient_id="p", attachment_id="a", av_report_id="r",
        media_type=PDF, source_sha256=HASH, content_length=5, content=b"SECRET",
    )
    assert not item.processing_allowed
    assert "SECRET" not in repr(item)
    with pytest.raises(FrozenInstanceError):
        item.processing_allowed = True
