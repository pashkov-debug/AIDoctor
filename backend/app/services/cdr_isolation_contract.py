"""6.4.1a: неизменяемый план изоляции будущего CDR, без исполнения.

В модуле НЕТ вызовов Docker, парсинга, CDR, клинического допуска и I/O.
Он принимает только снимок, полученный через аудитируемый шлюз 6.4.0.
Для настоящего CDR требуется отдельно одобренный образ, worker и запуск.
"""

import re
from dataclasses import dataclass, field
from hashlib import sha256
from hmac import compare_digest

from app.services.attachment_cdr_boundary import (
    CDR_INPUT_FORMATS,
    QuarantinedCDRCandidate,
)
from app.services.attachment_storage import MAX_FILE_BYTES

# Пиннинг по digest. Теги (:latest, :1.0) никогда не подходят.
# Только канонические нижнерегистровые имена с явным пространством имён.
_IMAGE_RE = re.compile(
    r"[a-z0-9]+(?:[._-][a-z0-9]+)*"
    r"(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*){1,5}"
    r"@sha256:[0-9a-f]{64}"
)
_HASH_RE = re.compile(r"[0-9a-f]{64}")

# Путь является контрактом с БУДУЩИМ согласованным CDR-образом.
# В AIDoctor сейчас нет образа с таким worker и нет его исполнения.
_WORKER_EXECUTABLE = "/usr/local/bin/aidoctor-cdr-worker"

_DOCKER_RESTRICTIONS = (
    "run",
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
    "--workdir=/tmp",
    "--env=HOME=/tmp",
    "--log-driver=none",
)


class CDRIsolationDenied(ValueError):
    """Запрошенную передачу данных в CDR-среду запрещено готовить."""


@dataclass(frozen=True)
class UnexecutedCDRPlan:
    """Только план. Не результат CDR и не пропуск в Context Builder.

    Входные байты не видны в repr, не сериализуются в CLI аргументы.
    Вызывать subprocess с этим объектом в 6.4.1a запрещено.
    """

    docker_argv: tuple[str, ...]
    media_type: str
    content_sha256: str
    content_length: int
    stdin_payload: bytes = field(repr=False)

    @property
    def executed(self) -> bool:
        return False

    @property
    def sanitized(self) -> bool:
        return False

    @property
    def processing_allowed(self) -> bool:
        return False


def build_unexecuted_cdr_plan(
    candidate: QuarantinedCDRCandidate,
    *,
    image_by_digest: str,
) -> UnexecutedCDRPlan:
    """Проверить снимок и построить ограниченную команду, НЕ запускать её.

    Не является заменой авторизации, блокировок и аудита 6.4.0.
    Образ может быть указан только для проектирования запуска: код
    никогда не обращается к Docker и не отправляет ему payload.
    """
    if not isinstance(candidate, QuarantinedCDRCandidate):
        raise CDRIsolationDenied("Требуется аудированный тип CDR-кандидата")
    if not isinstance(image_by_digest, str) or not _IMAGE_RE.fullmatch(image_by_digest):
        raise CDRIsolationDenied("CDR-образ обязан быть закреплён по SHA-256")

    if candidate.media_type not in CDR_INPUT_FORMATS.values():
        raise CDRIsolationDenied("Формат CDR-кандидата не разрешён")
    payload = candidate.content
    if not isinstance(payload, bytes):
        raise CDRIsolationDenied("Недопустимый тип входных байтов")
    if (
        type(candidate.content_length) is not int
        or not 1 <= candidate.content_length <= MAX_FILE_BYTES
        or len(payload) != candidate.content_length
    ):
        raise CDRIsolationDenied("Размер снимка не совпадает")
    if (
        not isinstance(candidate.source_sha256, str)
        or not _HASH_RE.fullmatch(candidate.source_sha256)
        or not compare_digest(sha256(payload).hexdigest(), candidate.source_sha256)
    ):
        raise CDRIsolationDenied("SHA-256 снимка не совпадает")

    # Путь к исходнику, patient_id и PHI не попадают в argv.
    return UnexecutedCDRPlan(
        docker_argv=("docker", *_DOCKER_RESTRICTIONS, image_by_digest, _WORKER_EXECUTABLE),
        media_type=candidate.media_type,
        content_sha256=candidate.source_sha256,
        content_length=candidate.content_length,
        stdin_payload=payload,
    )
