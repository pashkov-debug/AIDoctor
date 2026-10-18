"""6.3.1: ограниченный локальный ClamAV INSTREAM; ответ не снимает карантин.

Транспорт TCP не шифруется и не аутентифицируется. Допускается только loopback.
Любая ошибка, неизвестный ответ или незавершённый VERSION => scan error.
"""

import socket
import struct
from dataclasses import dataclass

from app.services.attachment_storage import CHUNK_SIZE, MAX_FILE_BYTES


class ClamdUnavailable(RuntimeError):
    """Нет достоверно завершённого протокольного ответа локального clamd."""


@dataclass(frozen=True)
class ClamdVerdict:
    status: str  # clean_reported | infected_reported; НЕ клинический допуск.
    engine_version: str


class ClamdScanner:
    """Принимает *байты*, никогда не путь к медицинскому файлу."""

    def __init__(self, *, port: int = 3310, timeout: float = 60.0):
        if not 1 <= port <= 65535:
            raise ValueError("Недопустимый порт ClamAV")
        if not 1 <= timeout <= 120:
            raise ValueError("Недопустимый таймаут ClamAV")
        self.port = port
        self.timeout = timeout

    def _connection(self) -> socket.socket:
        # Без возможности перенаправить медицинские байты на внешний IP.
        try:
            return socket.create_connection(("127.0.0.1", self.port), self.timeout)
        except OSError as exc:
            raise ClamdUnavailable("Локальный clamd недоступен") from exc

    @staticmethod
    def _read_record(sock: socket.socket, *, limit: int = 512) -> str:
        data = bytearray()
        while len(data) <= limit:
            block = sock.recv(1)
            if block == b"\x00":
                try:
                    return data.decode("ascii")
                except UnicodeDecodeError as exc:
                    raise ClamdUnavailable("Неверная кодировка ответа clamd") from exc
            if not block:
                break
            data.extend(block)
        raise ClamdUnavailable("Ответ clamd не завершён или слишком длинный")

    def scan(self, payload: bytes) -> ClamdVerdict:
        if not isinstance(payload, bytes) or not 1 <= len(payload) <= MAX_FILE_BYTES:
            raise ValueError("Недопустимый размер передаваемых байтов")
        try:
            with self._connection() as sock:
                sock.settimeout(self.timeout)
                sock.sendall(b"zINSTREAM\x00")
                for offset in range(0, len(payload), CHUNK_SIZE):
                    chunk = payload[offset : offset + CHUNK_SIZE]
                    sock.sendall(struct.pack(">I", len(chunk)))
                    sock.sendall(chunk)
                sock.sendall(b"\x00\x00\x00\x00")
                reply = self._read_record(sock)
            # Проверка версии не является проверкой подлинности сервера.
            with self._connection() as sock:
                sock.settimeout(self.timeout)
                sock.sendall(b"zVERSION\x00")
                version = self._read_record(sock, limit=200)
        except (OSError, TimeoutError) as exc:
            raise ClamdUnavailable("Ошибка транспорта clamd") from exc

        if not version.startswith("ClamAV ") or len(version) > 200:
            raise ClamdUnavailable("Версия clamd не подтверждена")
        if reply == "stream: OK":
            return ClamdVerdict("clean_reported", version)
        if reply.startswith("stream: ") and reply.endswith(" FOUND") and len(reply) > 14:
            return ClamdVerdict("infected_reported", version)
        raise ClamdUnavailable("Сканер не выдал допустимый результат")
