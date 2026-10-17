import io
import zipfile

import pytest
from app.services.attachment_storage import AttachmentRejected, AttachmentStorage


def test_pdf_save_and_content_hash(tmp_path):
    storage = AttachmentStorage(tmp_path)
    content = b"%PDF-1.7\n" + b"synthetic example"
    saved = storage.save(io.BytesIO(content), r"C:\temp\study.pdf")
    assert saved.filename == "study.pdf"
    assert saved.media_type == "application/pdf"
    assert saved.content_length == len(content)
    assert len(saved.content_sha256) == 64
    assert storage.path_for_download(saved.key).read_bytes() == content
    storage.delete(saved.key)
    assert storage.path_for_download(saved.key) is None


@pytest.mark.parametrize(
    ("filename", "content", "status"),
    [
        ("x.exe", b"MZ", 415),
        ("x.pdf", b"not a PDF", 415),
        ("x.pdf", b"", 422),
        ("x.png", b"%PDF-1.7\n", 415),
        ("../evil.pdf", b"bogus", 415),
    ],
)
def test_reject_unsupported_or_incorrect_data(tmp_path, filename, content, status):
    storage = AttachmentStorage(tmp_path)
    with pytest.raises(AttachmentRejected) as caught:
        storage.save(io.BytesIO(content), filename)
    assert caught.value.status_code == status
    assert not any(file.is_file() for file in tmp_path.rglob("*"))


def test_size_limit_cleans_temporary_file(tmp_path):
    storage = AttachmentStorage(tmp_path, max_bytes=8)
    with pytest.raises(AttachmentRejected) as caught:
        storage.save(io.BytesIO(b"%PDF-" + b"x" * 100), "large.pdf")
    assert caught.value.status_code == 413
    assert not any(file.is_file() for file in tmp_path.rglob("*"))


def test_path_traversal_key_rejected(tmp_path):
    storage = AttachmentStorage(tmp_path)
    with pytest.raises(ValueError, match="ключ"):
        storage.path_for_download("../secrets")


def test_docx_requires_word_document(tmp_path):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as item:
        item.writestr("[Content_Types].xml", "<Types/>")
        item.writestr("word/document.xml", "<document/>")
    storage = AttachmentStorage(tmp_path)
    saved = storage.save(io.BytesIO(archive.getvalue()), "document.docx")
    assert saved.media_type.endswith("wordprocessingml.document")
