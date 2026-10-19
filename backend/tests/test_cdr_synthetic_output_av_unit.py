"""6.5.0: негативные unit-проверки повторного AV синтетических CDR-выходов."""

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from app.services.attachment_av_policy import PreflightGatedScanner
from app.services.attachment_clamd import ClamdUnavailable, ClamdVerdict
from app.services.cdr_docx_synthetic_execution import SyntheticDOCXResult, synthetic_docx
from app.services.cdr_output_boundary import UntrustedCDROutput
from app.services.cdr_synthetic_execution import SyntheticCDRResult, synthetic_pdf
from app.services.cdr_synthetic_output_av import (
    CDRRepeatAVDenied,
    scan_synthetic_cdr_output,
)
from app.services.clamd_health import eicar_bytes
from app.workers import cdr_synthetic_av_once

VERSION = "ClamAV 1.5.4/12345/Sun Oct 18 06:24:14 2026"
NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
PDF = b"%PDF-1.5\nsynthetic output page\n%%EOF\n"


def output_result(*, docx=False):
    source_hash = hashlib.sha256(
        synthetic_docx() if docx else synthetic_pdf()
    ).hexdigest()
    output_hash = hashlib.sha256(PDF).hexdigest()
    output = UntrustedCDROutput(
        source_sha256=source_hash,
        output_sha256=output_hash,
        output_length=len(PDF),
        media_type="application/pdf",
        content=PDF,
    )
    cls = SyntheticDOCXResult if docx else SyntheticCDRResult
    return cls(
        source_sha256=source_hash,
        output_sha256=output_hash,
        output_length=len(PDF),
        output=output,
    )


class FakeEngine:
    def __init__(self, *, cdr_status="clean_reported", eicar_status="infected_reported"):
        self.calls = []
        self.cdr_status = cdr_status
        self.eicar_status = eicar_status
        self.change_version = False
        self.callback = None

    def scan(self, payload):
        self.calls.append(payload)
        if self.callback is not None:
            self.callback(payload)
        version = VERSION
        if self.change_version and len(self.calls) > 1:
            version = "ClamAV 1.5.5/12345/Sun Oct 18 06:24:14 2026"
        if payload == eicar_bytes():
            return ClamdVerdict(self.eicar_status, version)
        if self.cdr_status == "exception":
            raise ClamdUnavailable("секретные подробности")
        if self.cdr_status == "unexpected":
            raise RuntimeError("секретные подробности")
        return ClamdVerdict(self.cdr_status, version)


def gated(fake):
    return PreflightGatedScanner(fake, clock=lambda: NOW)


@pytest.mark.parametrize("docx", [False, True], ids=["pdf", "docx"])
def test_clean_scan_checks_eicar_before_and_after(docx):
    result = output_result(docx=docx)
    engine = FakeEngine()
    receipt = scan_synthetic_cdr_output(result, scanner=gated(engine))
    assert [x == eicar_bytes() for x in engine.calls] == [True, False, True]
    assert engine.calls[1] == PDF
    assert receipt.status == "clean_reported"
    assert receipt.reason_code is None
    assert receipt.engine_version == VERSION
    assert receipt.output_sha256 == hashlib.sha256(PDF).hexdigest()
    assert receipt.source_sha256 == result.source_sha256
    assert receipt.checked_at.tzinfo is not None
    assert receipt.processing_allowed is False
    assert receipt.trusted is False
    assert receipt.sanitized is False
    assert "synthetic output page" not in repr(receipt)


def test_infected_scan_never_clears():
    engine = FakeEngine(cdr_status="infected_reported")
    report = scan_synthetic_cdr_output(output_result(), scanner=gated(engine))
    assert report.status == "infected_reported"
    assert report.processing_allowed is False
    assert len(engine.calls) == 2


@pytest.mark.parametrize("status,reason", [
    ("exception", "scanner_unavailable"),
    ("unexpected", "scanner_unavailable"),
    ("weird", "scanner_unavailable"),
])
def test_scanner_error_is_fail_closed(status, reason):
    engine = FakeEngine(cdr_status=status)
    report = scan_synthetic_cdr_output(output_result(), scanner=gated(engine))
    assert report.status == "error"
    assert report.reason_code == reason
    assert report.engine_version is None


def test_eicar_failure_prevents_medical_payload_transmission():
    engine = FakeEngine(eicar_status="clean_reported")
    report = scan_synthetic_cdr_output(output_result(), scanner=gated(engine))
    assert report.status == "error"
    assert engine.calls == [eicar_bytes()]


def test_version_change_fails_closed():
    engine = FakeEngine()
    engine.change_version = True
    report = scan_synthetic_cdr_output(output_result(), scanner=gated(engine))
    assert report.status == "error"
    assert report.engine_version is None


@pytest.mark.parametrize("change", [
    "hash", "size", "type", "media", "empty", "source", "same", "raw", "eof",
], ids=[
    "hash", "size", "type", "media", "empty", "source", "same", "raw", "eof",
])
def test_tampered_output_refused_before_scanning(change):
    result = output_result()
    output = result.output
    if change == "hash":
        output = replace(output, output_sha256="a" * 64)
    elif change == "size":
        output = replace(output, output_length=len(PDF) + 1)
    elif change == "type":
        output = replace(output, content=bytearray(PDF))
    elif change == "media":
        output = replace(output, media_type="application/docx")
    elif change == "empty":
        output = replace(output, content=b"", output_length=0)
    elif change == "source":
        output = replace(output, source_sha256="0" * 64)
    elif change == "same":
        output = replace(output, source_sha256=output.output_sha256)
    elif change == "raw":
        raw = b"not PDF %%EOF"
        output = replace(
            output, content=raw, output_length=len(raw),
            output_sha256=hashlib.sha256(raw).hexdigest(),
        )
    else:
        raw = b"%PDF-1.5\nno end"
        output = replace(
            output, content=raw, output_length=len(raw),
            output_sha256=hashlib.sha256(raw).hexdigest(),
        )
    result = replace(
        result,
        output=output,
        source_sha256=output.source_sha256,
        output_sha256=output.output_sha256,
        output_length=output.output_length,
    )
    engine = FakeEngine()
    with pytest.raises(CDRRepeatAVDenied):
        scan_synthetic_cdr_output(result, scanner=gated(engine))
    assert engine.calls == []


def test_non_synthetic_input_rejected():
    with pytest.raises(CDRRepeatAVDenied):
        scan_synthetic_cdr_output(SimpleNamespace(output=PDF), scanner=gated(FakeEngine()))


def test_ungated_scanner_rejected():
    engine = FakeEngine()
    with pytest.raises(CDRRepeatAVDenied):
        scan_synthetic_cdr_output(output_result(), scanner=engine)
    assert engine.calls == []


def test_output_changed_during_scan_rejected():
    result = output_result()
    engine = FakeEngine()

    def mutate(payload):
        if payload == PDF:
            object.__setattr__(result, "output_sha256", "f" * 64)

    engine.callback = mutate
    receipt = scan_synthetic_cdr_output(result, scanner=gated(engine))
    assert receipt.status == "error"
    assert receipt.reason_code == "output_changed"
    assert receipt.engine_version is None


@pytest.mark.parametrize("docx", [False, True])
def test_worker_only_runs_explicitly(monkeypatch, docx):
    image_flag = "--docx-image-id" if docx else "--pdf-image-id"
    args = [image_flag, "sha256:" + "f" * 64]
    monkeypatch.setattr(
        cdr_synthetic_av_once, "settings",
        SimpleNamespace(attachment_clamd_enabled=True),
    )
    with pytest.raises(SystemExit) as info:
        cdr_synthetic_av_once.main(args)
    assert info.value.code == 2


def test_worker_disabled_by_default(monkeypatch):
    monkeypatch.setattr(
        cdr_synthetic_av_once, "settings",
        SimpleNamespace(attachment_clamd_enabled=False),
    )
    with pytest.raises(SystemExit) as info:
        cdr_synthetic_av_once.main(
            ["--once", "--pdf-image-id", "sha256:" + "f" * 64]
        )
    assert info.value.code == 2


@pytest.mark.parametrize("status,expected", [
    ("clean_reported", 0), ("infected_reported", 1), ("error", 1),
])
def test_worker_reports_status_without_payload(monkeypatch, capsys, status, expected):
    from app.services.cdr_synthetic_output_av import SyntheticCDRAVReceipt

    monkeypatch.setattr(
        cdr_synthetic_av_once, "settings",
        SimpleNamespace(attachment_clamd_enabled=True),
    )
    monkeypatch.setattr(
        cdr_synthetic_av_once, "run_synthetic_pdf_cdr",
        lambda **kw: output_result(),
    )
    monkeypatch.setattr(cdr_synthetic_av_once, "ClamdScanner", lambda: FakeEngine())
    monkeypatch.setattr(cdr_synthetic_av_once, "PreflightGatedScanner", lambda scanner: scanner)
    monkeypatch.setattr(
        cdr_synthetic_av_once,
        "scan_synthetic_cdr_output",
        lambda result, scanner: SyntheticCDRAVReceipt(
            source_sha256=result.source_sha256,
            output_sha256=result.output_sha256,
            output_length=result.output_length,
            status=status,
            reason_code=None,
            engine_version=VERSION,
            checked_at=NOW,
        ),
    )
    code = cdr_synthetic_av_once.main(
        ["--once", "--pdf-image-id", "sha256:" + "f" * 64]
    )
    assert code == expected
    text = capsys.readouterr().out
    assert "synthetic output page" not in text
    assert "запрет обработки сохранены" in text


def test_worker_does_not_leak_cdr_error(monkeypatch, capsys):
    from app.services.cdr_synthetic_execution import CDRExecutionDenied

    monkeypatch.setattr(
        cdr_synthetic_av_once, "settings",
        SimpleNamespace(attachment_clamd_enabled=True),
    )
    monkeypatch.setattr(
        cdr_synthetic_av_once,
        "run_synthetic_docx_cdr",
        lambda **kw: (_ for _ in ()).throw(CDRExecutionDenied("PRIVATE SECRET")),
    )
    assert cdr_synthetic_av_once.main(
        ["--once", "--docx-image-id", "sha256:" + "f" * 64]
    ) == 1
    assert "PRIVATE SECRET" not in capsys.readouterr().out
