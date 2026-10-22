"""6.4.2b: запуск только синтетического DOCX, fake Docker без сети."""

import hashlib

import pytest
from app.services import cdr_docx_synthetic_execution as execution
from app.services.cdr_synthetic_execution import CDRExecutionDenied
from app.workers import cdr_docx_synthetic_once

IMAGE_ID = "sha256:" + "a" * 64


def test_synthetic_plan_narrow_and_deterministic():
    plan = execution.synthetic_docx_plan(IMAGE_ID)
    assert plan.content_sha256 == hashlib.sha256(plan.stdin_payload).hexdigest()
    assert plan.media_type.endswith("wordprocessingml.document")
    assert plan.processing_allowed is False
    assert plan.executed is False
    assert plan.docker_argv[-2:] == (IMAGE_ID, "/usr/local/bin/aidoctor-docx-cdr-worker")
    assert "--read-only" in plan.docker_argv
    assert "--network=none" in plan.docker_argv
    assert "--cap-drop=ALL" in plan.docker_argv
    assert "--security-opt=no-new-privileges" in plan.docker_argv
    assert "--log-driver=none" in plan.docker_argv
    assert "--user=65534:65534" in plan.docker_argv
    assert "--memory=2048m" in plan.docker_argv
    assert "--ulimit=nofile=256:256" in plan.docker_argv
    assert not any(
        x.startswith(("--mount", "--volume", "--publish", "-v", "-p")) for x in plan.docker_argv
    )


@pytest.mark.parametrize(
    "image_id",
    [
        "aidoctor-docx:synthetic",
        "sha256:abcd",
        "sha256:" + "A" * 64,
        "sha256:" + "f" * 64 + " --privileged",
        "org/image@sha256:" + "f" * 64,
        "",
        None,
    ],
)
def test_image_injection_rejected(image_id):
    with pytest.raises(CDRExecutionDenied):
        execution.synthetic_docx_plan(image_id)


def test_container_mock_success_untrusted(monkeypatch):
    converted = b"%PDF-1.5\nchanged synthetic\n%%EOF\n"
    seen = {}

    def fake_run(argv, payload, **kwargs):
        seen["argv"] = argv
        assert payload == execution.synthetic_docx()
        return converted

    monkeypatch.setattr(execution, "_capture_bounded_process", fake_run)
    monkeypatch.setattr(execution.subprocess, "run", lambda *args, **kw: None)
    result = execution.run_synthetic_docx_cdr(image_id=IMAGE_ID)
    assert result.output_sha256 == hashlib.sha256(converted).hexdigest()
    assert result.output.content == converted
    assert result.output.sanitized is False
    assert result.output.trusted is False
    assert result.output.processing_allowed is False
    assert result.processing_allowed is False
    assert any(arg.startswith("--name=aidoctor-docx-cdr-") for arg in seen["argv"])


@pytest.mark.parametrize("raw", [b"", b"DOCX", b"%PDF-1.4\n"])
def test_invalid_output_fail_closed(monkeypatch, raw):
    monkeypatch.setattr(execution, "_capture_bounded_process", lambda *args, **kwargs: raw)
    monkeypatch.setattr(execution.subprocess, "run", lambda *args, **kwargs: None)
    with pytest.raises(CDRExecutionDenied, match="CDR-выход"):
        execution.run_synthetic_docx_cdr(image_id=IMAGE_ID)


def test_cleanup_even_on_failed_container(monkeypatch):
    called = []

    def fail(*args, **kwargs):
        raise CDRExecutionDenied("SECRET_PRIVATE")

    monkeypatch.setattr(execution, "_capture_bounded_process", fail)
    monkeypatch.setattr(
        execution.subprocess,
        "run",
        lambda argv, **kwargs: called.append(argv),
    )
    with pytest.raises(CDRExecutionDenied):
        execution.run_synthetic_docx_cdr(image_id=IMAGE_ID)
    assert len(called) == 1
    assert called[0][:3] == ["docker", "rm", "--force"]


def test_cli_requires_explicit_flag_and_hides_secret(monkeypatch, capsys):
    with pytest.raises(SystemExit) as error:
        cdr_docx_synthetic_once.main(["--image-id", IMAGE_ID])
    assert error.value.code == 2
    monkeypatch.setattr(
        cdr_docx_synthetic_once,
        "run_synthetic_docx_cdr",
        lambda **kwargs: (_ for _ in ()).throw(CDRExecutionDenied("SECRET_PRIVATE")),
    )
    assert cdr_docx_synthetic_once.main(["--run-synthetic", "--image-id", IMAGE_ID]) == 1
    assert "SECRET_PRIVATE" not in capsys.readouterr().out
