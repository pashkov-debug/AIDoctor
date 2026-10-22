"""Этап 6.2: файловая предпроверка не тождественна антивирусу."""

import io
import zipfile
from types import SimpleNamespace

import pytest
from app.services.attachment_security import (
    AV_STATUS_NOT_SCANNED,
    ProcessingProhibited,
    _read_quarantined_file,
    require_processing_clearance,
)
from app.services.attachment_storage import AttachmentRejected, AttachmentStorage


def _attachment(saved, **overrides):
    fields = {
        "filename": saved.filename,
        "media_type": saved.media_type,
        "content_length": saved.content_length,
        "content_sha256": saved.content_sha256,
        "storage_key": saved.key,
        "extraction_status": "quarantined",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_precheck_is_not_av_or_processing_permission(tmp_path):
    storage = AttachmentStorage(tmp_path)
    saved = storage.save(io.BytesIO(b"%PDF-1.7\nSYNTHETIC"), "scan.pdf")
    result = _read_quarantined_file(storage, _attachment(saved))
    assert result.accepted
    assert result.reason is None
    assert result.length == saved.content_length
    assert result.sha256 == saved.content_sha256
    assert AV_STATUS_NOT_SCANNED == "not_scanned"
    with pytest.raises(ProcessingProhibited):
        require_processing_clearance(_attachment(saved), None)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"media_type": "image/png"}, "invalid_metadata"),
        ({"content_length": -1}, "invalid_metadata"),
        ({"content_sha256": "NOT-A-SHA"}, "invalid_metadata"),
        ({"storage_key": "../../etc/passwd"}, "invalid_storage_key"),
    ],
)
def test_invalid_metadata_cannot_pass(tmp_path, overrides, expected):
    storage = AttachmentStorage(tmp_path)
    saved = storage.save(io.BytesIO(b"%PDF-1.7\nSYNTHETIC"), "scan.pdf")
    result = _read_quarantined_file(storage, _attachment(saved, **overrides))
    assert not result.accepted
    assert result.reason == expected


def test_tampering_or_missing_file_is_rejected(tmp_path):
    storage = AttachmentStorage(tmp_path)
    saved = storage.save(io.BytesIO(b"%PDF-1.7\nSYNTHETIC"), "scan.pdf")
    path = storage.path_for_download(saved.key)
    path.write_bytes(b"%PDF-1.7\nMALICIOUS")
    changed = _read_quarantined_file(storage, _attachment(saved))
    assert changed.reason == "hash_mismatch"
    assert not changed.accepted
    storage.delete(saved.key)
    missing = _read_quarantined_file(storage, _attachment(saved))
    assert missing.reason == "storage_missing"


def test_size_mismatch_and_invalid_signature(tmp_path):
    storage = AttachmentStorage(tmp_path)
    saved = storage.save(io.BytesIO(b"%PDF-1.7\nSYNTHETIC"), "scan.pdf")
    assert (
        _read_quarantined_file(
            storage, _attachment(saved, content_length=saved.content_length + 1)
        ).reason
        == "size_mismatch"
    )
    path = storage.path_for_download(saved.key)
    path.write_bytes(b"not a pdf")
    import hashlib

    fake = _attachment(
        saved,
        content_sha256=hashlib.sha256(b"not a pdf").hexdigest(),
        content_length=len(b"not a pdf"),
    )
    assert _read_quarantined_file(storage, fake).reason == "signature_mismatch"


def test_symlink_refused_when_supported(tmp_path):
    storage = AttachmentStorage(tmp_path / "store")
    saved = storage.save(io.BytesIO(b"%PDF-1.7\nSYNTHETIC"), "scan.pdf")
    path = storage.path_for_download(saved.key)
    data = path.read_bytes()
    target = tmp_path / "outside"
    target.write_bytes(data)
    path.unlink()
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Символические ссылки недоступны в текущем окружении")
    assert _read_quarantined_file(storage, _attachment(saved)).reason == "storage_missing"


def test_docx_archive_traversal_and_bomb_metadata_rejected(tmp_path):
    storage = AttachmentStorage(tmp_path)
    for name, malicious in [
        ("../outside.xml", "payload"),
        ("C:/absolute.xml", "payload"),
        ("word/vbaProject.bin", "payload"),
        ("word/huge.xml", "x" * (1024 * 1024)),
    ]:
        contents = io.BytesIO()
        with zipfile.ZipFile(contents, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")
            archive.writestr(name, malicious)
        with pytest.raises(AttachmentRejected):
            storage.save(io.BytesIO(contents.getvalue()), "synthetic.docx")


def test_processing_gate_refuses_even_prechecked_state(tmp_path):
    storage = AttachmentStorage(tmp_path)
    saved = storage.save(io.BytesIO(b"%PDF-1.7\nSYNTHETIC"), "scan.pdf")
    review = SimpleNamespace(status="prechecked_quarantined", reason_code=None)
    with pytest.raises(ProcessingProhibited):
        require_processing_clearance(_attachment(saved), review)
