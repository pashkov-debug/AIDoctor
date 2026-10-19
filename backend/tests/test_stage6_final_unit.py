"""6.6 FINAL: закрытый клинический допуск даже после технических AV/CDR-операций."""

import hashlib
import io
from types import SimpleNamespace

import pytest
from app.services import attachment_av_scan
from app.services.attachment_security import (
    ProcessingProhibited,
    _read_quarantined_file,
    require_processing_clearance,
)
from app.services.attachment_storage import AttachmentStorage
from app.services.cdr_output_boundary import capture_untrusted_cdr_output
from app.services.cdr_synthetic_execution import synthetic_pdf, synthetic_plan

OUTPUT = b"%PDF-1.5\\nsynthetic-rasterized-test\\n%%EOF\\n"
IMAGE_ID = "sha256:" + "0" * 64


@pytest.mark.parametrize(
    ("state", "review"),
    [
        ("quarantined", None),
        ("quarantined", "prechecked_quarantined"),
        ("quarantined", "rejected"),
        ("extracted", "prechecked_quarantined"),
        ("released", "clean_reported"),
    ],
)
def test_no_legacy_status_grants_processing(state, review):
    attachment = SimpleNamespace(
        extraction_status=state,
        extracted_text_ref=None,
    )
    row = None if review is None else SimpleNamespace(status=review)
    with pytest.raises(ProcessingProhibited):
        require_processing_clearance(attachment, row)


def test_file_integrity_and_clinical_gate_are_independent(tmp_path):
    storage = AttachmentStorage(tmp_path)
    saved = storage.save(io.BytesIO(synthetic_pdf()), "synthetic.pdf")
    attachment = SimpleNamespace(
        filename=saved.filename,
        media_type=saved.media_type,
        content_length=saved.content_length,
        content_sha256=saved.content_sha256,
        storage_key=saved.key,
        extraction_status="quarantined",
        extracted_text_ref=None,
    )
    inspected = _read_quarantined_file(storage, attachment)
    assert inspected.accepted
    assert inspected.payload is None
    assert inspected.sha256 == saved.content_sha256
    with pytest.raises(ProcessingProhibited):
        require_processing_clearance(
            attachment, SimpleNamespace(status="prechecked_quarantined")
        )

    path = storage.path_for_download(saved.key)
    modified = bytearray(path.read_bytes())
    modified[-10] ^= 1
    assert len(modified) == saved.content_length
    path.write_bytes(modified)
    inspected = _read_quarantined_file(storage, attachment)
    assert not inspected.accepted
    assert inspected.reason == "hash_mismatch"


def test_synthetic_cdr_output_is_neither_trusted_nor_usable():
    plan = synthetic_plan(IMAGE_ID)
    artifact = capture_untrusted_cdr_output(plan, io.BytesIO(OUTPUT))
    assert artifact.source_sha256 == hashlib.sha256(synthetic_pdf()).hexdigest()
    assert artifact.output_sha256 == hashlib.sha256(OUTPUT).hexdigest()
    assert artifact.trusted is False
    assert artifact.sanitized is False
    assert artifact.processing_allowed is False
    assert OUTPUT.decode("ascii") not in repr(artifact)
    with pytest.raises(ProcessingProhibited):
        require_processing_clearance(
            SimpleNamespace(extraction_status="quarantined"),
            SimpleNamespace(status="prechecked_quarantined"),
        )


@pytest.mark.parametrize(
    "bad_scan",
    [
        lambda _data: (_ for _ in ()).throw(RuntimeError("private AV exception")),
        lambda _data: (_ for _ in ()).throw(TimeoutError("AV timed out")),
        lambda _data: None,
        lambda _data: object(),
    ],
    ids=["runtime-error", "timeout", "none", "invalid-object"],
)
def test_adapter_error_always_reaches_database_report(monkeypatch, bad_scan):
    snapshot = SimpleNamespace(content=b"synthetic-scanner-input")
    captured = []

    def fake_capture(*_args, **_kwargs):
        return snapshot

    def fake_persist(*_args, **kwargs):
        captured.append(kwargs)
        return kwargs

    monkeypatch.setattr(
        attachment_av_scan, "capture_quarantined_scan_input", fake_capture
    )
    monkeypatch.setattr(attachment_av_scan, "_persist_report", fake_persist)
    result = attachment_av_scan.scan_quarantined_attachment(
        object(),
        patient_id="patient",
        attachment_id="attachment",
        actor_id="admin",
        storage=object(),
        scanner=SimpleNamespace(scan=bad_scan),
    )
    assert result == captured[0]
    assert len(captured) == 1
    assert result["scanner_status"] == "error"
    assert result["failure"] == "scanner_unavailable"
    assert result["engine_version"] is None
