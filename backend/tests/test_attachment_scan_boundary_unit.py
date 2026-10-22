"""6.3.0: неизменяемость буфера и отсутствие фиктивного AV-допуска."""

import io
from types import SimpleNamespace

import pytest
from app.services.attachment_security import (
    ProcessingProhibited,
    _read_quarantined_file,
    require_processing_clearance,
)
from app.services.attachment_storage import AttachmentStorage


def test_capture_payload_only_when_explicitly_requested(tmp_path):
    payload = b"%PDF-1.7\\nQUARANTINE-ONLY"
    storage = AttachmentStorage(tmp_path)
    saved = storage.save(io.BytesIO(payload), "quarantine.pdf")
    attachment = SimpleNamespace(
        filename=saved.filename,
        media_type=saved.media_type,
        content_length=saved.content_length,
        content_sha256=saved.content_sha256,
        storage_key=saved.key,
    )
    normal = _read_quarantined_file(storage, attachment)
    assert normal.accepted
    assert normal.payload is None

    captured = _read_quarantined_file(storage, attachment, capture_payload=True)
    assert captured.accepted
    assert captured.payload == payload
    assert isinstance(captured.payload, bytes)
    storage.path_for_download(saved.key).write_bytes(b"CHANGED")
    assert captured.payload == payload
    assert _read_quarantined_file(storage, attachment, capture_payload=True).payload is None
    with pytest.raises(ProcessingProhibited):
        require_processing_clearance(attachment, None)


def test_invalid_source_never_returns_raw_payload(tmp_path):
    storage = AttachmentStorage(tmp_path)
    saved = storage.save(io.BytesIO(b"%PDF-1.7\\nSOURCE"), "quarantine.pdf")
    attachment = SimpleNamespace(
        filename=saved.filename,
        media_type=saved.media_type,
        content_length=saved.content_length + 1,
        content_sha256=saved.content_sha256,
        storage_key=saved.key,
    )
    inspection = _read_quarantined_file(storage, attachment, capture_payload=True)
    assert not inspection.accepted
    assert inspection.reason == "size_mismatch"
    assert inspection.payload is None
