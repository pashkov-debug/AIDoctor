"""6.4.2b: Docker smoke-test только для встроенного синтетического DOCX.

Это НЕ клиническая обработка DOCX: ни API, ни файлов пациента, ни вызова
QuarantinedCDRCandidate, ни снятия карантина. LibreOffice доступен только
в одноразовом контейнере; выход всегда UntrustedCDROutput.
"""

import hashlib
import io
import re
import subprocess
import zipfile
from dataclasses import dataclass
from uuid import uuid4

from app.services import cdr_isolation_contract
from app.services.cdr_output_boundary import UntrustedCDROutput, capture_untrusted_cdr_output
from app.services.cdr_synthetic_execution import (
    CDRExecutionDenied,
    _capture_bounded_process,
)

_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_LABEL = "AIDoctor synthetic DOCX test only"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_DOCX_WORKER = "/usr/local/bin/aidoctor-docx-cdr-worker"

# Ограничения существующего PDF-пути не меняем. LibreOffice выделяем
# ограниченный tmpfs и память отдельно; сеть, привилегии и mounts закрыты.
_REPLACE = {
    "--memory=1024m": "--memory=2048m",
    "--memory-swap=1024m": "--memory-swap=2048m",
    "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777": (
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=256m,mode=1777"
    ),
}
_DOCKER_RESTRICTIONS = tuple(
    _REPLACE.get(value, value) for value in cdr_isolation_contract._DOCKER_RESTRICTIONS
) + ("--ulimit=nofile=256:256",)


@dataclass(frozen=True)
class SyntheticDOCXResult:
    source_sha256: str
    output_sha256: str
    output_length: int
    output: UntrustedCDROutput

    @property
    def processing_allowed(self) -> bool:
        return False


def synthetic_docx() -> bytes:
    """Компактный OOXML с одной синтетической строкой, без личных данных."""
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.'
            'document.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
            'officeDocument" '
            'Target="word/document.xml"/></Relationships>'
        ),
        "word/document.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{_LABEL}</w:t></w:r></w:p></w:body>"
            "</w:document>"
        ),
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, xml in parts.items():
            archive.writestr(name, xml.encode("utf-8"))
    return stream.getvalue()


def synthetic_docx_plan(image_id: str) -> cdr_isolation_contract.UnexecutedCDRPlan:
    """Принимаем только локальный image ID, а не тег, путь или параметры Docker."""
    if not isinstance(image_id, str) or not _IMAGE_ID_RE.fullmatch(image_id):
        raise CDRExecutionDenied("Нужен полный локальный SHA-256 ID образа")
    payload = synthetic_docx()
    return cdr_isolation_contract.UnexecutedCDRPlan(
        docker_argv=("docker", *_DOCKER_RESTRICTIONS, image_id, _DOCX_WORKER),
        media_type=_DOCX_MIME,
        content_sha256=hashlib.sha256(payload).hexdigest(),
        content_length=len(payload),
        stdin_payload=payload,
    )


def run_synthetic_docx_cdr(
    *,
    image_id: str,
    timeout: float = 150,
) -> SyntheticDOCXResult:
    """Запуск исключительно встроенной фикстуры с принудительной очисткой Docker."""
    plan = synthetic_docx_plan(image_id)
    container_name = f"aidoctor-docx-cdr-{uuid4().hex}"
    argv = (*plan.docker_argv[:-2], f"--name={container_name}", *plan.docker_argv[-2:])
    try:
        output = _capture_bounded_process(argv, plan.stdin_payload, timeout=timeout)
    finally:
        try:
            subprocess.run(
                ["docker", "rm", "--force", container_name],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        untrusted = capture_untrusted_cdr_output(plan, io.BytesIO(output))
    except ValueError as exc:
        raise CDRExecutionDenied("CDR-выход не прошёл проверку") from exc
    return SyntheticDOCXResult(
        source_sha256=plan.content_sha256,
        output_sha256=untrusted.output_sha256,
        output_length=untrusted.output_length,
        output=untrusted,
    )
