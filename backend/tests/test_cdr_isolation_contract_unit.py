"""6.4.1a: отказ по умолчанию, закреплённый образ и граница CDR."""

from dataclasses import FrozenInstanceError
from hashlib import sha256

import pytest
from app.services.attachment_cdr_boundary import QuarantinedCDRCandidate
from app.services.attachment_storage import MAX_FILE_BYTES
from app.services.cdr_isolation_contract import (
    CDRIsolationDenied,
    build_unexecuted_cdr_plan,
)

IMAGE = "ghcr.io/example/aidoctor-cdr@sha256:" + "a" * 64
PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def make_candidate(payload=b"%PDF-1.7\\nsynthetic", media_type=PDF, **changes):
    attrs = dict(
        patient_id="patient-private",
        attachment_id="attachment-private",
        av_report_id="report-private",
        media_type=media_type,
        source_sha256=sha256(payload).hexdigest(),
        content_length=len(payload),
        content=payload,
    )
    attrs.update(changes)
    return QuarantinedCDRCandidate(**attrs)


@pytest.mark.parametrize("media", [PDF, DOCX])
def test_plan_does_not_execute_or_release_and_hides_phi(media):
    candidate = make_candidate(b"secret-patient-unique", media)
    result = build_unexecuted_cdr_plan(candidate, image_by_digest=IMAGE)
    assert result.media_type == media
    assert result.content_sha256 == candidate.source_sha256
    assert result.content_length == candidate.content_length
    assert result.stdin_payload == candidate.content
    assert result.executed is False
    assert result.sanitized is False
    assert result.processing_allowed is False
    assert b"secret-patient-unique" not in repr(result).encode()
    assert "secret-patient-unique" not in " ".join(result.docker_argv)
    assert "patient-private" not in " ".join(result.docker_argv)
    assert "attachment-private" not in " ".join(result.docker_argv)
    with pytest.raises(FrozenInstanceError):
        result.processing_allowed = True


def test_command_restricts_network_mounts_processes_memory_and_privileges():
    args = build_unexecuted_cdr_plan(make_candidate(), image_by_digest=IMAGE).docker_argv
    assert args[0] == "docker"
    assert args[1] == "run"
    assert args[-2:] == (IMAGE, "/usr/local/bin/aidoctor-cdr-worker")
    for required in (
        "--rm",
        "--interactive",
        "--pull=never",
        "--network=none",
        "--ipc=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--user=65534:65534",
        "--pids-limit=64",
        "--memory=1024m",
        "--memory-swap=1024m",
        "--cpus=1",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
        "--log-driver=none",
    ):
        assert required in args
    assert not any(v.startswith(("--volume", "--mount", "-v", "-p", "--publish", "--privileged"))
                   for v in args)


@pytest.mark.parametrize(
    "image",
    [
        "",
        "ghcr.io/example/cdr:latest",
        "alpine:latest",
        "ghcr.io/example/cdr",
        "ghcr.io/example/cdr@sha256:abc",
        "ghcr.io/example/cdr@sha256:" + "A" * 64,
        "ghcr.io/example/cdr@sha256:" + "f" * 64 + " --privileged",
        "ghcr.io/example/../cdr@sha256:" + "f" * 64,
        "ghcr.io/example/cdr@sha256:" + "f" * 63,
        "ghcr.io/example/cdr@sha256:" + "g" * 64,
    ],
)
def test_unpinned_or_injected_image_is_rejected(image):
    with pytest.raises(CDRIsolationDenied, match="закреплён"):
        build_unexecuted_cdr_plan(make_candidate(), image_by_digest=image)


def test_missing_candidate_or_untrusted_type_is_rejected():
    with pytest.raises(CDRIsolationDenied):
        build_unexecuted_cdr_plan(None, image_by_digest=IMAGE)
    with pytest.raises(CDRIsolationDenied):
        build_unexecuted_cdr_plan(object(), image_by_digest=IMAGE)


@pytest.mark.parametrize("wrong_media", ["text/plain", "application/zip", "", None])
def test_disallowed_format(wrong_media):
    with pytest.raises(CDRIsolationDenied, match="Формат"):
        build_unexecuted_cdr_plan(make_candidate(media_type=wrong_media), image_by_digest=IMAGE)


@pytest.mark.parametrize(
    "changes",
    [
        {"content_length": 1},
        {"content_length": 0},
        {"content_length": True},
        {"content_length": MAX_FILE_BYTES + 1},
        {"content": b""},
        {"content": bytearray(b"abc")},
        {"content": "not bytes"},
        {"source_sha256": "0" * 64},
        {"source_sha256": "A" * 64},
        {"source_sha256": "notahash"},
        {"source_sha256": None},
    ],
)
def test_malformed_candidate_is_rejected(changes):
    with pytest.raises(CDRIsolationDenied):
        build_unexecuted_cdr_plan(make_candidate(**changes), image_by_digest=IMAGE)


def test_exact_hash_and_size_prevent_single_byte_tampering():
    original = b"%PDF-1.7\\nsynthetic"
    altered = original[:-1] + b"X"
    with pytest.raises(CDRIsolationDenied, match="SHA-256"):
        build_unexecuted_cdr_plan(
            make_candidate(payload=original, content=altered),
            image_by_digest=IMAGE,
        )


def test_does_not_call_docker_or_touch_file_system(monkeypatch):
    import subprocess

    def deny(*args, **kwargs):
        raise AssertionError("I/O forbidden for CDR plan")

    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(subprocess, "run", deny)
    plan = build_unexecuted_cdr_plan(make_candidate(), image_by_digest=IMAGE)
    assert plan.executed is False
