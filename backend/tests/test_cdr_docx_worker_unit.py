"""6.4.2b: DOCX-worker, без запуска Docker/LibreOffice в unit-тестах."""

import io
import subprocess
import zipfile
from pathlib import Path

import pytest
from app.services.cdr_docx_synthetic_execution import synthetic_docx
from cdr_image import docx_worker


def _mutate(
    payload: bytes,
    changes: dict[str, bytes],
    add: dict[str, bytes] | None = None,
) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(payload))
    stream = io.BytesIO()
    with source, zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for name in source.namelist():
            target.writestr(name, changes.get(name, source.read(name)))
        for name, value in (add or {}).items():
            target.writestr(name, value)
    return stream.getvalue()


def test_accept_only_synthetic_docx():
    payload = synthetic_docx()
    docx_worker.validate_synthetic_docx(payload)
    assert payload.startswith(b"PK\x03\x04")


@pytest.mark.parametrize("payload", [b"", b"PK\x03\x04broken", b"%PDF-1.4", b"x" * 10])
def test_reject_invalid_archives(payload):
    with pytest.raises(docx_worker.DOCXConversionDenied):
        docx_worker.validate_synthetic_docx(payload)


def test_reject_excessive_input_without_archive_open():
    with pytest.raises(docx_worker.DOCXConversionDenied):
        docx_worker.validate_synthetic_docx(b"PK\x03\x04" + b"x" * docx_worker.MAX_BYTES)


@pytest.mark.parametrize(
    ("extra_name", "content"),
    [
        ("word/vbaProject.bin", b"malicious"),
        ("word/embeddings/obj1.bin", b"obj"),
        ("word/_rels/document.xml.rels", b"<Relationships/>"),
        ("../../attack", b"no"),
        ("word/media/a.png", b"no"),
    ],
)
def test_reject_added_parts(extra_name, content):
    payload = _mutate(synthetic_docx(), {}, {extra_name: content})
    with pytest.raises(docx_worker.DOCXConversionDenied):
        docx_worker.validate_synthetic_docx(payload)


def test_reject_external_relationship():
    original = synthetic_docx()
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        rels = archive.read("_rels/.rels")
    changed = rels.replace(
        b'Target="word/document.xml"',
        b'Target="https://example.net/document.xml" TargetMode="External"',
    )
    with pytest.raises(docx_worker.DOCXConversionDenied):
        docx_worker.validate_synthetic_docx(_mutate(original, {"_rels/.rels": changed}))


def test_reject_dde_field():
    docx = synthetic_docx()
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        xml = archive.read("word/document.xml")
    changed = xml.replace(b"<w:body>", b'<w:body><w:fldSimple w:instr="DDEAUTO"/>')
    with pytest.raises(docx_worker.DOCXConversionDenied):
        docx_worker.validate_synthetic_docx(_mutate(docx, {"word/document.xml": changed}))


def test_reject_doctype():
    docx = synthetic_docx()
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        xml = archive.read("word/document.xml")
    xml = xml.replace(b"<w:document", b"<!DOCTYPE w:document><w:document")
    with pytest.raises(docx_worker.DOCXConversionDenied):
        docx_worker.validate_synthetic_docx(_mutate(docx, {"word/document.xml": xml}))


def test_reject_changed_synthetic_text():
    docx = synthetic_docx()
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        xml = archive.read("word/document.xml")
    xml = xml.replace(b"AIDoctor synthetic", b"Patient secret")
    with pytest.raises(docx_worker.DOCXConversionDenied):
        docx_worker.validate_synthetic_docx(_mutate(docx, {"word/document.xml": xml}))


def test_reject_bomb_ratio():
    docx = synthetic_docx()
    with zipfile.ZipFile(io.BytesIO(docx)) as archive:
        xml = archive.read("word/document.xml")
    xml += b" " * 1_000_000
    with pytest.raises(docx_worker.DOCXConversionDenied):
        docx_worker.validate_synthetic_docx(_mutate(docx, {"word/document.xml": xml}))


def test_conversion_runs_headless_then_raster(monkeypatch):
    calls = []
    output = b"%PDF-1.5\nregenerated\n%%EOF\n"

    def fake_run(argv, **kwargs):
        calls.append(argv)
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == 70
        assert "-env:UserInstallation=" in argv[1]
        assert "--headless" in argv
        Path(argv[argv.index("--outdir") + 1], "input.pdf").write_bytes(
            b"%PDF-1.4\nlo synthetic\n%%EOF\n"
        )
        return subprocess.CompletedProcess(argv, 0)

    def fake_raster(payload):
        assert payload.startswith(b"%PDF-")
        calls.append(["pdftoppm"])
        return output

    monkeypatch.setattr(docx_worker.subprocess, "run", fake_run)
    monkeypatch.setattr(docx_worker.pdf_worker, "convert_pdf", fake_raster)
    assert docx_worker.convert_docx(synthetic_docx()) == output
    assert calls[0][0] == "libreoffice"
    assert calls[1] == ["pdftoppm"]


def test_conversion_rejects_no_libreoffice_output(monkeypatch):
    monkeypatch.setattr(
        docx_worker.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    with pytest.raises(docx_worker.DOCXConversionDenied, match="не создал"):
        docx_worker.convert_docx(synthetic_docx())


def test_conversion_rejects_lo_failure_without_details(monkeypatch):
    def fail(args, **kwargs):
        raise subprocess.CalledProcessError(1, args, b"SECRET")

    monkeypatch.setattr(docx_worker.subprocess, "run", fail)
    with pytest.raises(docx_worker.DOCXConversionDenied) as error:
        docx_worker.convert_docx(synthetic_docx())
    assert "SECRET" not in str(error.value)


def test_conversion_rejects_raster_failure(monkeypatch):
    def fake_run(argv, **kwargs):
        Path(argv[argv.index("--outdir") + 1], "input.pdf").write_bytes(b"%PDF-1.4\n%%EOF")

    monkeypatch.setattr(docx_worker.subprocess, "run", fake_run)
    monkeypatch.setattr(
        docx_worker.pdf_worker,
        "convert_pdf",
        lambda data: (_ for _ in ()).throw(docx_worker.pdf_worker.ConversionDenied()),
    )
    with pytest.raises(docx_worker.DOCXConversionDenied, match="растеризовать"):
        docx_worker.convert_docx(synthetic_docx())
