"""6.4.2: тесты реального алгоритма PDF→JPEG→PDF с изолированными утилитами."""

from pathlib import Path

import pytest
from app.services.cdr_synthetic_execution import synthetic_pdf
from cdr_image import worker


@pytest.mark.parametrize("payload", [b"", b"DOCX", b"PK\x03\x04", b"not a PDF"])
def test_worker_rejects_unsupported_formats(payload):
    with pytest.raises(worker.ConversionDenied):
        worker.convert_pdf(payload)


def test_worker_rejects_oversized_without_parsing():
    with pytest.raises(worker.ConversionDenied):
        worker.convert_pdf(b"%PDF-" + b"0" * worker.MAX_BYTES)


@pytest.mark.parametrize(
    ("info", "rejected"),
    [
        (b"Pages: 9\nEncrypted: no\n", True),
        (b"Pages: 0\nEncrypted: no\n", True),
        (b"Pages: 1\nEncrypted: yes\n", True),
        (b"Pages: a\nEncrypted: no\n", True),
        (b"Pages: 1\n", True),
        (b"Pages: 1\nEncrypted: no\n", False),
    ],
)
def test_metadata_limits(monkeypatch, tmp_path, info, rejected):
    monkeypatch.setattr(worker, "_run", lambda command: info)
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(synthetic_pdf())
    if rejected:
        with pytest.raises(worker.ConversionDenied):
            worker._pdf_page_count(path)
    else:
        assert worker._pdf_page_count(path) == 1


def test_worker_calls_renderer_and_rebuilder(monkeypatch):
    tools_called = []
    regenerated = b"%PDF-1.4\nchanged-synthetic\n%%EOF\n"

    def fake_run(command):
        tools_called.append(command[0])
        if command[0] == "pdfinfo":
            return b"Pages: 1\nEncrypted: no\n"
        if command[0] == "pdftoppm":
            Path(command[-1] + "-1.jpg").write_bytes(b"\xff\xd8\xffDATA")
            return b""
        if command[0] == "img2pdf":
            Path(command[command.index("--output") + 1]).write_bytes(regenerated)
            return b""
        raise AssertionError("unknown utility")

    monkeypatch.setattr(worker, "_run", fake_run)
    assert worker.convert_pdf(synthetic_pdf()) == regenerated
    assert tools_called == ["pdfinfo", "pdftoppm", "img2pdf"]


def test_worker_rejects_missing_raster_pages(monkeypatch):
    def fake_run(command):
        if command[0] == "pdfinfo":
            return b"Pages: 1\nEncrypted: no\n"
        return b""

    monkeypatch.setattr(worker, "_run", fake_run)
    with pytest.raises(worker.ConversionDenied, match="растеризованных"):
        worker.convert_pdf(synthetic_pdf())


def test_worker_rejects_bad_jpeg(monkeypatch):
    def fake_run(command):
        if command[0] == "pdfinfo":
            return b"Pages: 1\nEncrypted: no\n"
        if command[0] == "pdftoppm":
            Path(command[-1] + "-1.jpg").write_bytes(b"garbage")
        return b""

    monkeypatch.setattr(worker, "_run", fake_run)
    with pytest.raises(worker.ConversionDenied, match="изображение"):
        worker.convert_pdf(synthetic_pdf())
