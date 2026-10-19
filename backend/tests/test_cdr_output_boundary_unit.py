"""6.4.1b: недоверенный CDR-выход не даёт права на обработку."""

import io
from dataclasses import FrozenInstanceError
from hashlib import sha256

import pytest
from app.services.attachment_cdr_boundary import QuarantinedCDRCandidate
from app.services.attachment_storage import MAX_FILE_BYTES
from app.services.cdr_isolation_contract import build_unexecuted_cdr_plan
from app.services.cdr_output_boundary import (
    CDROutputRejected,
    capture_untrusted_cdr_output,
)

IMAGE = "ghcr.io/example/aidoctor-cdr@sha256:" + "c" * 64
PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF\n"
CONVERTED = b"%PDF-1.7\n1 0 obj<</Changed true>>endobj\n%%EOF\n"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def make_plan(content=PDF, *, media_type="application/pdf"):
    candidate = QuarantinedCDRCandidate(
        patient_id="patient-private",
        attachment_id="attachment-private",
        av_report_id="report-private",
        media_type=media_type,
        source_sha256=sha256(content).hexdigest(),
        content_length=len(content),
        content=content,
    )
    return build_unexecuted_cdr_plan(candidate, image_by_digest=IMAGE)


@pytest.mark.parametrize("source_media", ["application/pdf", DOCX], ids=["pdf", "docx"])
def test_untrusted_output_never_grants_clearance(source_media):
    source = PDF if source_media == "application/pdf" else b"PK synthetic docx"
    plan = make_plan(source, media_type=source_media)
    result = capture_untrusted_cdr_output(plan, io.BytesIO(CONVERTED))
    assert result.source_sha256 == sha256(source).hexdigest()
    assert result.output_sha256 == sha256(CONVERTED).hexdigest()
    assert result.output_length == len(CONVERTED)
    assert result.content == CONVERTED
    assert result.media_type == "application/pdf"
    assert result.sanitized is False
    assert result.trusted is False
    assert result.processing_allowed is False
    assert "Changed" not in repr(result)
    assert "patient-private" not in repr(result)
    with pytest.raises(FrozenInstanceError):
        result.processing_allowed = True


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"", "Пустой"),
        (b"garbage", "завершённый PDF"),
        (b"%PDF-1.7\nstream ...", "завершённый PDF"),
        (b"garbage %%EOF", "завершённый PDF"),
        (PDF, "неизменённый оригинал"),
    ],
    ids=["empty", "nonpdf", "truncated", "forged-end", "passthrough"],
)
def test_invalid_output_fails_closed(payload, reason):
    with pytest.raises(CDROutputRejected, match=reason):
        capture_untrusted_cdr_output(make_plan(), io.BytesIO(payload))


def test_end_marker_must_be_near_end():
    payload = b"%PDF-1.7\n%%EOF\n" + b"Z" * 1100
    with pytest.raises(CDROutputRejected, match="завершённый"):
        capture_untrusted_cdr_output(make_plan(), io.BytesIO(payload))


@pytest.mark.parametrize(
    "format_name",
    [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "",
        None,
    ],
)
def test_output_format_is_pdf_only(format_name):
    with pytest.raises(CDROutputRejected, match="должен быть PDF"):
        capture_untrusted_cdr_output(
            make_plan(), io.BytesIO(CONVERTED), media_type=format_name
        )


class InfiniteSyntheticStream:
    """Не создаёт многомегабайтный параметр pytest/PYTEST_CURRENT_TEST."""

    def read(self, length):
        return b"x" * length


def test_oversized_stream_is_rejected_without_unbounded_read():
    with pytest.raises(CDROutputRejected, match="превышает лимит"):
        capture_untrusted_cdr_output(make_plan(), InfiniteSyntheticStream())


def test_exact_maximum_size_can_be_captured_but_stays_untrusted():
    header, footer = b"%PDF-1.7\n", b"\n%%EOF\n"
    payload = header + b"Z" * (MAX_FILE_BYTES - len(header) - len(footer)) + footer
    assert len(payload) == MAX_FILE_BYTES
    result = capture_untrusted_cdr_output(make_plan(), io.BytesIO(payload))
    assert result.output_length == MAX_FILE_BYTES
    assert result.processing_allowed is False


@pytest.mark.parametrize("bad_stream", [None, 3, object()])
def test_invalid_stream_is_rejected(bad_stream):
    with pytest.raises(CDROutputRejected, match="бинарный поток"):
        capture_untrusted_cdr_output(make_plan(), bad_stream)


class TextStream:
    def read(self, length):
        return "%PDF-1.7\n%%EOF"


class BrokenStream:
    def read(self, length):
        raise OSError("confidential path")


def test_text_stream_fails_closed():
    with pytest.raises(CDROutputRejected, match="небинарные"):
        capture_untrusted_cdr_output(make_plan(), TextStream())


def test_read_failure_does_not_leak_exception_detail():
    with pytest.raises(CDROutputRejected, match="Невозможно прочитать"):
        capture_untrusted_cdr_output(make_plan(), BrokenStream())


@pytest.mark.parametrize(
    "change",
    [
        {"source_sha256": "0" * 64},
        {"source_sha256": "invalid"},
        {"content_length": 1},
        {"content_length": True},
        {"stdin_payload": b"modified"},
        {"media_type": "image/jpeg"},
    ],
)
def test_mutated_plan_is_rejected(change):
    plan = make_plan()
    prop_map = {
        "source_sha256": "content_sha256",
        "content_length": "content_length",
        "stdin_payload": "stdin_payload",
        "media_type": "media_type",
    }
    for field, value in change.items():
        object.__setattr__(plan, prop_map[field], value)
    with pytest.raises(CDROutputRejected):
        capture_untrusted_cdr_output(plan, io.BytesIO(CONVERTED))


def test_type_spoofing_is_rejected():
    with pytest.raises(CDROutputRejected, match="исходный план"):
        capture_untrusted_cdr_output(object(), io.BytesIO(CONVERTED))


def test_capture_does_not_run_docker_or_use_db(monkeypatch):
    import subprocess

    def forbidden(*args, **kwargs):
        raise AssertionError("Запуск Docker запрещён")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    assert not capture_untrusted_cdr_output(
        make_plan(), io.BytesIO(CONVERTED)
    ).processing_allowed
