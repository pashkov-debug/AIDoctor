"""Закрытое файловое хранилище медицинских вложений (локальный MVP)."""

import hashlib
import os
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from app.core.config import PROJECT_ROOT

CHUNK_SIZE = 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
}


class AttachmentRejected(Exception):
    """Недопустимое вложение: безопасное сообщение и HTTP-код."""

    def __init__(self, message: str, status_code: int = 415) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class StoredAttachment:
    key: str
    filename: str
    media_type: str
    content_length: int
    content_sha256: str


def safe_filename(filename: str | None) -> str:
    if not filename:
        raise AttachmentRejected("Не указано имя файла", 422)
    result = unicodedata.normalize("NFC", filename.replace("\\", "/").split("/")[-1])
    if (
        result in {"", ".", ".."}
        or len(result) > 255
        or any(ord(char) < 32 or ord(char) == 127 for char in result)
    ):
        raise AttachmentRejected("Недопустимое имя файла", 422)
    return result


def matches_signature(stream: BinaryIO, extension: str) -> bool:
    """Ограниченная проверка формата из уже открытого источника; НЕ AV/CDR."""
    stream.seek(0)
    head = stream.read(64)

    signatures = {
        ".pdf": head.startswith(b"%PDF-"),
        ".doc": head.startswith(bytes.fromhex("d0cf11e0a1b11ae1")),
        ".jpg": head.startswith(b"\xff\xd8\xff"),
        ".jpeg": head.startswith(b"\xff\xd8\xff"),
        ".png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        ".webp": head.startswith(b"RIFF") and head[8:12] == b"WEBP",
        ".tif": head.startswith((b"II*\x00", b"MM\x00*")),
        ".tiff": head.startswith((b"II*\x00", b"MM\x00*")),
        ".wav": head.startswith(b"RIFF") and head[8:12] == b"WAVE",
        ".mp3": head.startswith(b"ID3")
        or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0),
        ".ogg": head.startswith(b"OggS"),
        ".flac": head.startswith(b"fLaC"),
        ".m4a": len(head) >= 12
        and head[4:8] == b"ftyp"
        and head[8:12] in {b"M4A ", b"M4B ", b"isom", b"iso2", b"mp41", b"mp42"},
    }
    if extension != ".docx":
        return signatures.get(extension, False)

    try:
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            entries = archive.infolist()
            if len(entries) > 3000 or sum(e.file_size for e in entries) > 80 * 1024 * 1024:
                return False
            names = [e.filename for e in entries]
            if len(names) != len(set(names)):
                return False
            for entry in entries:
                name = entry.filename.replace("\\", "/")
                if (
                    name.startswith("/")
                    or ".." in name.split("/")
                    or ":" in name.split("/", 1)[0]
                    or name.startswith("./")
                    or name.lower().endswith("vbaproject.bin")
                    or entry.flag_bits & 0x1  # Запароленный/зашифрованный ZIP.
                    or entry.file_size > 80 * 1024 * 1024
                    or entry.file_size > 1000 * max(entry.compress_size, 1)
                    or (
                        entry.create_system == 3
                        and (entry.external_attr >> 16) & 0o170000 == 0o120000
                    )  # Unix symlink внутри архива.
                ):
                    return False
            return {"[Content_Types].xml", "word/document.xml"}.issubset(names)
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError):
        return False


def _check_signature(path: Path, extension: str) -> bool:
    with path.open("rb") as stream:
        return matches_signature(stream, extension)


class AttachmentStorage:
    """Оригиналы за пределами статической раздачи, по непрозрачным UUID-ключам."""

    def __init__(self, directory: str | Path, max_bytes: int = MAX_FILE_BYTES) -> None:
        path = Path(directory).expanduser()
        self.root = (path if path.is_absolute() else PROJECT_ROOT / path).resolve()
        self.max_bytes = max_bytes
        if self.max_bytes <= 0:
            raise ValueError("max_bytes должен быть положительным")
        self.root.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.root.chmod(0o700)

    def _path(self, key: str) -> Path:
        try:
            parsed = UUID(key)
        except (ValueError, AttributeError, TypeError) as exc:
            raise ValueError("Недопустимый ключ вложения") from exc
        if parsed.version != 4 or parsed.hex != key:
            raise ValueError("Недопустимый ключ вложения")
        return self.root / key[:2] / key

    def save(self, source: BinaryIO, filename: str | None) -> StoredAttachment:
        clean_name = safe_filename(filename)
        extension = Path(clean_name).suffix.lower()
        if extension not in MEDIA_TYPES:
            raise AttachmentRejected("Тип файла не поддерживается")

        key = uuid4().hex
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        digest = hashlib.sha256()
        length = 0

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=".upload-", suffix=".part", dir=destination.parent, delete=False
            ) as output:
                temporary = Path(output.name)
                while block := source.read(CHUNK_SIZE):
                    length += len(block)
                    if length > self.max_bytes:
                        raise AttachmentRejected("Размер файла превышает лимит", 413)
                    digest.update(block)
                    output.write(block)
                output.flush()
                os.fsync(output.fileno())

            if length == 0:
                raise AttachmentRejected("Пустой файл не допускается", 422)
            if not _check_signature(temporary, extension):
                raise AttachmentRejected("Содержимое не соответствует типу файла")
            if os.name != "nt":
                temporary.chmod(0o600)
            # Уникальный UUID исключает практически возможную коллизию имён.
            if destination.exists():
                raise FileExistsError("Коллизия ключей вложений")
            os.replace(temporary, destination)
            return StoredAttachment(
                key=key,
                filename=clean_name,
                media_type=MEDIA_TYPES[extension],
                content_length=length,
                content_sha256=digest.hexdigest(),
            )
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def path_for_download(self, key: str) -> Path | None:
        path = self._path(key)
        if path.is_symlink() or not path.is_file():
            return None
        return path

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)
