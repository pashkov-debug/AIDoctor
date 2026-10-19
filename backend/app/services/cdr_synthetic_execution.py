"""6.4.2: локальный CDR smoke-test ТОЛЬКО на встроенном синтетическом PDF.

Контейнер действительно растеризует страницы и собирает новый PDF.
Нет доступа к реальным вложениям, PostgreSQL, клиническим API и Context Builder.
Результат остаётся UntrustedCDROutput без разрешения на обработку.
"""

import hashlib
import io
import re
import subprocess
import threading
import time
from uuid import uuid4
from dataclasses import dataclass
from hmac import compare_digest

from app.services import cdr_isolation_contract
from app.services.cdr_output_boundary import (
    MAX_CDR_OUTPUT_BYTES,
    UntrustedCDROutput,
    capture_untrusted_cdr_output,
)

_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SYNTHETIC_LABEL = "AIDoctor synthetic CDR test only"
_MAX_INPUT = 20 * 1024 * 1024


class CDRExecutionDenied(RuntimeError):
    """Только обобщённое сообщение без вывода файлов и stdout/stderr движка."""


@dataclass(frozen=True)
class SyntheticCDRResult:
    source_sha256: str
    output_sha256: str
    output_length: int
    output: UntrustedCDROutput

    @property
    def processing_allowed(self) -> bool:
        return False


def synthetic_pdf() -> bytes:
    """Минимальный корректный одностраничный PDF, не содержащий данных пациентов."""
    content = (
        b"BT /F1 18 Tf 60 730 Td (" + _SYNTHETIC_LABEL.encode("ascii") + b") Tj ET\n"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content + b"endstream",
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, item in enumerate(objects, start=1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode() + item + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n".encode() + b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref).encode() + b"\n%%EOF\n"
    )
    return bytes(result)


def synthetic_plan(image_id: str) -> cdr_isolation_contract.UnexecutedCDRPlan:
    """Привязка к ЛОКАЛЬНОМУ SHA-256 image ID, а не произвольному Docker tag.

    Не заменяет build_unexecuted_cdr_plan для настоящих аудированных кандидатов.
    """
    if not isinstance(image_id, str) or _IMAGE_ID_RE.fullmatch(image_id) is None:
        raise CDRExecutionDenied("Нужен точный локальный ID образа sha256:<64 hex>")
    payload = synthetic_pdf()
    return cdr_isolation_contract.UnexecutedCDRPlan(
        docker_argv=("docker", *cdr_isolation_contract._DOCKER_RESTRICTIONS, image_id, cdr_isolation_contract._WORKER_EXECUTABLE),
        media_type="application/pdf",
        content_sha256=hashlib.sha256(payload).hexdigest(),
        content_length=len(payload),
        stdin_payload=payload,
    )


def _capture_bounded_process(
    argv: tuple[str, ...],
    payload: bytes,
    *,
    timeout: float,
    output_limit: int = MAX_CDR_OUTPUT_BYTES,
) -> bytes:
    """Одновременно послать stdin и ограниченно принять stdout.

    Отбрасываем stderr целиком: сканер не должен передавать в журналы
    содержимое потенциально опасного документа. Поддерживается Windows.
    """
    if not argv or not isinstance(payload, bytes):
        raise CDRExecutionDenied("Некорректный запрос к CDR")
    if not 0 < len(payload) <= _MAX_INPUT or not 0 < output_limit <= MAX_CDR_OUTPUT_BYTES:
        raise CDRExecutionDenied("Недопустимый размер данных CDR")
    if not 0 < timeout <= 180:
        raise CDRExecutionDenied("Недопустимый таймаут CDR")

    try:
        process = subprocess.Popen(
            argv,
            shell=False,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except (OSError, ValueError) as exc:
        raise CDRExecutionDenied("Не удалось запустить CDR-контейнер") from exc

    output = bytearray()
    failure = threading.Event()
    overflow = threading.Event()

    def send() -> None:
        try:
            assert process.stdin is not None
            process.stdin.write(payload)
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            failure.set()
        finally:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass

    def receive() -> None:
        try:
            assert process.stdout is not None
            while True:
                chunk = process.stdout.read(65536)
                if not chunk:
                    break
                if len(output) + len(chunk) > output_limit:
                    overflow.set()
                    break
                output.extend(chunk)
        except (OSError, ValueError):
            failure.set()

    producer = threading.Thread(target=send, daemon=True, name="cdr-stdin")
    consumer = threading.Thread(target=receive, daemon=True, name="cdr-stdout")
    producer.start()
    consumer.start()
    started = time.monotonic()
    code = None
    try:
        while time.monotonic() - started < timeout:
            if overflow.is_set():
                break
            try:
                code = process.wait(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                continue
        if code is None:
            raise CDRExecutionDenied("CDR превышен лимит времени или вывода")
        producer.join(timeout=1)
        consumer.join(timeout=1)
        if producer.is_alive() or consumer.is_alive():
            raise CDRExecutionDenied("CDR-потоки не завершились")
        if code != 0 or failure.is_set() or overflow.is_set():
            raise CDRExecutionDenied("CDR завершился с ошибкой")
        return bytes(output)
    finally:
        if process.poll() is None:
            process.kill()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        if process.stdin is not None and not producer.is_alive():
            process.stdin.close()
        if process.stdout is not None and not consumer.is_alive():
            process.stdout.close()


def run_synthetic_pdf_cdr(
    *,
    image_id: str,
    timeout: float = 90,
) -> SyntheticCDRResult:
    """Настоящий Docker-run, но только со встроенным синтетическим документом.

    Функция не принимает путь/имя/байты пользовательского файла.
    Не может использоваться для медицинских вложений без нового контракта.
    """
    plan = synthetic_plan(image_id)
    # При завершении Docker CLI по timeout демон может оставить контейнер.
    # Непрозрачное имя позволяет прервать именно этот синтетический процесс.
    container_name = f"aidoctor-cdr-{uuid4().hex}"
    docker_args = (*plan.docker_argv[:-2], f"--name={container_name}", *plan.docker_argv[-2:])
    try:
        output_bytes = _capture_bounded_process(
            docker_args, plan.stdin_payload, timeout=timeout
        )
    finally:
        # docker rm -f безопасен и для уже удалённого (--rm) контейнера.
        # Не показываем stderr Docker и не используем shell.
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
        result = capture_untrusted_cdr_output(plan, io.BytesIO(output_bytes))
    except ValueError as exc:
        raise CDRExecutionDenied("Выход CDR не прошёл проверку") from exc
    if compare_digest(result.output_sha256, plan.content_sha256):
        raise CDRExecutionDenied("CDR не изменил документ")
    return SyntheticCDRResult(
        source_sha256=plan.content_sha256,
        output_sha256=result.output_sha256,
        output_length=result.output_length,
        output=result,
    )
