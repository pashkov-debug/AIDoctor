"""6.4.2: никакой тест не читает медицинские вложения и не требует Docker."""

import hashlib
import sys

import pytest
from app.services import cdr_synthetic_execution as execution
from app.workers import cdr_synthetic_once

IMAGE_ID = "sha256:" + "a" * 64


def test_synthetic_pdf_valid_and_contains_only_known_label():
    payload = execution.synthetic_pdf()
    assert payload.startswith(b"%PDF-1.4")
    assert payload.endswith(b"%%EOF\n")
    assert b"AIDoctor synthetic CDR test only" in payload
    assert len(payload) < 4096


def test_synthetic_pdf_xref_is_structurally_valid():
    payload = execution.synthetic_pdf()
    tail = payload.split(b"startxref\n", 1)[1]
    xref = int(tail.split(b"\n", 1)[0])
    assert payload[xref : xref + 5] == b"xref\n"
    assert b"0 6\n" in payload[xref : xref + 16]


def test_pinned_local_id_and_isolation_and_no_phi():
    plan = execution.synthetic_plan(IMAGE_ID)
    args = plan.docker_argv
    assert args[0:2] == ("docker", "run")
    assert args[-2] == IMAGE_ID
    assert args[-1] == "/usr/local/bin/aidoctor-cdr-worker"
    assert "--network=none" in args
    assert "--read-only" in args
    assert "--cap-drop=ALL" in args
    assert "--log-driver=none" in args
    assert not any(arg.startswith(("-v", "--volume", "--mount", "-p", "--publish")) for arg in args)
    assert plan.executed is False
    assert plan.processing_allowed is False
    assert plan.content_sha256 == hashlib.sha256(plan.stdin_payload).hexdigest()
    assert "AIDoctor synthetic" not in str(args)


@pytest.mark.parametrize(
    "image_id",
    [
        "aidoctor-cdr:latest",
        "sha256:123",
        "sha256:" + "A" * 64,
        "sha256:" + "f" * 64 + " --privileged",
        "aidoctor/worker@sha256:" + "a" * 64,
        "",
        None,
    ],
)
def test_reject_image_injection(image_id):
    with pytest.raises(execution.CDRExecutionDenied):
        execution.synthetic_plan(image_id)


def test_fail_closed_if_output_unmodified(monkeypatch):
    monkeypatch.setattr(
        execution,
        "_capture_bounded_process",
        lambda *args, **kwargs: execution.synthetic_pdf(),
    )
    with pytest.raises(execution.CDRExecutionDenied, match="Выход CDR"):
        execution.run_synthetic_pdf_cdr(image_id=IMAGE_ID)


def test_fail_closed_if_output_not_pdf(monkeypatch):
    monkeypatch.setattr(execution, "_capture_bounded_process", lambda *args, **kwargs: b"garbage")
    with pytest.raises(execution.CDRExecutionDenied, match="Выход CDR"):
        execution.run_synthetic_pdf_cdr(image_id=IMAGE_ID)


def test_result_stays_untrusted_with_mock_worker(monkeypatch):
    source = execution.synthetic_pdf()
    converted = b"%PDF-1.4\n1 0 obj<</Type /Catalog>>endobj\n%%EOF\n"
    assert converted != source
    monkeypatch.setattr(
        execution,
        "_capture_bounded_process",
        lambda argv, payload, **kwargs: converted,
    )
    result = execution.run_synthetic_pdf_cdr(image_id=IMAGE_ID)
    assert result.output.content == converted
    assert result.output.sanitized is False
    assert result.output.processing_allowed is False
    assert result.processing_allowed is False


def _call_python(script, *, size_limit=1024, timeout=2):
    return execution._capture_bounded_process(
        (sys.executable, "-S", "-c", script),
        b"synthetic",
        timeout=timeout,
        output_limit=size_limit,
    )


def test_bounded_process_success():
    assert (
        _call_python(
            "import sys; data=sys.stdin.buffer.read(); sys.stdout.buffer.write(data[::-1])"
        )
        == b"citehtnys"
    )


def test_bounded_process_rejects_large_stdout():
    with pytest.raises(execution.CDRExecutionDenied):
        _call_python(
            "import sys; sys.stdin.buffer.read(); "
            "sys.stdout.buffer.write(b'X'*2048); sys.stdout.buffer.flush()",
            size_limit=128,
        )


def test_bounded_process_kills_hung_worker():
    with pytest.raises(execution.CDRExecutionDenied, match="времени"):
        _call_python(
            "import sys,time; sys.stdin.buffer.read(); time.sleep(4)",
            timeout=0.25,
        )


def test_bounded_process_fails_on_nonzero():
    with pytest.raises(execution.CDRExecutionDenied, match="ошибкой"):
        _call_python("import sys; sys.stdin.buffer.read(); sys.exit(3)")


def test_do_not_echo_secret_stderr():
    with pytest.raises(execution.CDRExecutionDenied) as captured:
        _call_python(
            "import sys; sys.stderr.write('SECRET_MEDICAL'); sys.stdin.buffer.read(); sys.exit(2)"
        )
    assert "SECRET_MEDICAL" not in str(captured.value)


@pytest.mark.parametrize(
    "timeout",
    [0, -1, 181, float("inf")],
)
def test_invalid_timeouts_rejected_without_start(timeout):
    with pytest.raises(execution.CDRExecutionDenied):
        execution._capture_bounded_process(
            (sys.executable, "-c", "print(1)"),
            b"synthetic",
            timeout=timeout,
        )


def test_cli_no_silent_execution(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        cdr_synthetic_once.main(["--image-id", IMAGE_ID])
    assert exc.value.code == 2
    monkeypatch.setattr(
        cdr_synthetic_once,
        "run_synthetic_pdf_cdr",
        lambda **kwargs: (_ for _ in ()).throw(execution.CDRExecutionDenied("SECRET")),
    )
    assert cdr_synthetic_once.main(["--run-synthetic", "--image-id", IMAGE_ID]) == 1
    assert "SECRET" not in capsys.readouterr().out
