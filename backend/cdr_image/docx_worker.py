#!/usr/bin/env python3
"""Синтетический DOCX → LibreOffice PDF → растровый PDF в отдельном контейнере.

Этот worker намеренно принимает узкий поднабор OOXML: три XML-части,
без ссылок, медиа, макросов и внедрений. НЕ использовать для медицинских DOCX.
stdin/stdout — двоичные потоки; никогда не логировать содержимое документа.
"""

import io
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

if __package__:
    from . import worker as pdf_worker
else:
    import worker as pdf_worker

MAX_BYTES = 20 * 1024 * 1024
MAX_XML_BYTES = 2 * 1024 * 1024
_ALLOWED_PARTS = frozenset({"[Content_Types].xml", "_rels/.rels", "word/document.xml"})
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_DOC_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
_DOC_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
_ALLOWED_WORD_TAGS = {f"{{{_DOC_NS}}}{tag}" for tag in ("document", "body", "p", "r", "t")}
_LABEL = "AIDoctor synthetic DOCX test only"
_TIMEOUT = 70


class DOCXConversionDenied(ValueError):
    """Формат или операция не прошли ограничения синтетического CDR."""


def _xml_from_part(data: bytes) -> ET.Element:
    if (
        not 0 < len(data) <= MAX_XML_BYTES
        or b"<!DOCTYPE" in data.upper()
        or b"<!ENTITY" in data.upper()
    ):
        raise DOCXConversionDenied("Недопустимый XML")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise DOCXConversionDenied("Некорректный XML") from exc


def _bounded_parts(payload: bytes) -> dict[str, bytes]:
    if (
        not isinstance(payload, bytes)
        or not 0 < len(payload) <= MAX_BYTES
        or not payload.startswith(b"PK\x03\x04")
    ):
        raise DOCXConversionDenied("Только ограниченный DOCX")
    result: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            infos = archive.infolist()
            if len(infos) != len(_ALLOWED_PARTS):
                raise DOCXConversionDenied("Неизвестные части DOCX")
            for item in infos:
                if (
                    item.filename not in _ALLOWED_PARTS
                    or item.filename in result
                    or item.is_dir()
                    or item.flag_bits & 1
                    or item.compress_type not in (zipfile.ZIP_DEFLATED, zipfile.ZIP_STORED)
                    or not 0 < item.file_size <= MAX_XML_BYTES
                    or item.file_size > 50 * max(item.compress_size, 1)
                    or (item.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise DOCXConversionDenied("Недопустимая часть DOCX")
                with archive.open(item) as handle:
                    data = handle.read(MAX_XML_BYTES + 1)
                if len(data) != item.file_size:
                    raise DOCXConversionDenied("Размер части DOCX не совпадает")
                result[item.filename] = data
    except (OSError, RuntimeError, zipfile.BadZipFile, EOFError) as exc:
        raise DOCXConversionDenied("Невозможно разобрать архив DOCX") from exc
    if result.keys() != _ALLOWED_PARTS:
        raise DOCXConversionDenied("Неполный DOCX")
    return result


def validate_synthetic_docx(payload: bytes) -> None:
    """Проверить лишь УЗКИЙ тестовый документ; это не доказательство безопасности."""
    parts = _bounded_parts(payload)
    types = _xml_from_part(parts["[Content_Types].xml"])
    if types.tag != f"{{{_CT_NS}}}Types":
        raise DOCXConversionDenied("Неверный формат Content Types")
    defaults = {}
    overrides = {}
    for item in types:
        if item.tag == f"{{{_CT_NS}}}Default":
            defaults[item.attrib.get("Extension")] = item.attrib.get("ContentType")
        elif item.tag == f"{{{_CT_NS}}}Override":
            overrides[item.attrib.get("PartName")] = item.attrib.get("ContentType")
        else:
            raise DOCXConversionDenied("Посторонний тип содержимого")
    if (
        len(types) != 3
        or defaults
        != {
            "rels": "application/vnd.openxmlformats-package.relationships+xml",
            "xml": "application/xml",
        }
        or overrides != {"/word/document.xml": _DOC_MIME}
    ):
        raise DOCXConversionDenied("Неожиданные типы DOCX")

    rels = _xml_from_part(parts["_rels/.rels"])
    if (
        rels.tag != f"{{{_REL_NS}}}Relationships"
        or len(rels) != 1
        or rels[0].tag != f"{{{_REL_NS}}}Relationship"
        or rels[0].attrib
        != {
            "Id": "rId1",
            "Type": _OFFICE_REL,
            "Target": "word/document.xml",
        }
    ):
        raise DOCXConversionDenied("Недопустимые связи DOCX")

    doc = _xml_from_part(parts["word/document.xml"])
    if doc.tag != f"{{{_DOC_NS}}}document" or doc.attrib:
        raise DOCXConversionDenied("Недопустимая структура DOCX")
    if any(element.tag not in _ALLOWED_WORD_TAGS for element in doc.iter()):
        raise DOCXConversionDenied("Недопустимые элементы Word")
    hierarchy = ("body", "p", "r", "t")
    cursor = doc
    for tag in hierarchy:
        if len(cursor) != 1 or cursor[0].tag != f"{{{_DOC_NS}}}{tag}":
            raise DOCXConversionDenied("Неожиданный OOXML-документ")
        cursor = cursor[0]
    if cursor.text != _LABEL or len(cursor) != 0:
        raise DOCXConversionDenied("DOCX не является синтетической фикстурой")
    if any(element.attrib for element in doc.iter()):
        raise DOCXConversionDenied("Неожиданные атрибуты Word")
    if any(
        (element.text and element.text.strip() and element is not cursor)
        or (element.tail and element.tail.strip())
        for element in doc.iter()
    ):
        raise DOCXConversionDenied("Неожиданный текст XML")


def convert_docx(payload: bytes) -> bytes:
    """Настоящий конвертер с растрированием; только синтетический DOCX."""
    validate_synthetic_docx(payload)
    with tempfile.TemporaryDirectory(dir="/tmp", prefix="aidoctor-docx-") as temp:
        directory = Path(temp)
        source = directory / "input.docx"
        source.write_bytes(payload)
        target = directory / "input.pdf"
        profile = (directory / "lo-profile").as_uri()
        try:
            subprocess.run(
                [
                    "libreoffice",
                    f"-env:UserInstallation={profile}",
                    "--headless",
                    "--nologo",
                    "--nodefault",
                    "--nofirststartwizard",
                    "--convert-to",
                    "pdf:writer_pdf_Export",
                    "--outdir",
                    str(directory),
                    str(source),
                ],
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                timeout=_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise DOCXConversionDenied("DOCX-конвертер завершился с ошибкой") from exc
        if not target.is_file() or not 0 < target.stat().st_size <= MAX_BYTES:
            raise DOCXConversionDenied("DOCX-конвертер не создал ограниченный PDF")
        pdf = target.read_bytes()
        try:
            return pdf_worker.convert_pdf(pdf)
        except pdf_worker.ConversionDenied as exc:
            raise DOCXConversionDenied("Не удалось растеризовать PDF") from exc


def main() -> int:
    try:
        payload = sys.stdin.buffer.read(MAX_BYTES + 1)
        result = convert_docx(payload)
        sys.stdout.buffer.write(result)
        sys.stdout.buffer.flush()
    except (DOCXConversionDenied, OSError, MemoryError, ValueError, OverflowError):
        print("CDR отклонил синтетический DOCX", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
