"""Проверка опасных настроек до первого Docker Compose запуска (только stdlib)."""

import argparse
import os
import re
from pathlib import Path


def check_configuration(filename: Path) -> list[str]:
    errors = []
    if not filename.is_file():
        return [f"Не найден файл {filename}"]
    if os.name != "nt" and filename.stat().st_mode & 0o077:
        errors.append("Файл конфигурации должен иметь права 0600")
    props: dict[str, str] = {}
    for raw in filename.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            errors.append("Строка без знака '='")
            continue
        key, value = line.split("=", 1)
        if key in props:
            errors.append(f"Повторная переменная {key}")
        props[key] = value.strip()
    password = props.get("DB_PASSWORD", "")
    if len(password) < 32 or re.fullmatch(r"[A-Za-z0-9_-]+", password) is None:
        errors.append("DB_PASSWORD: требуется 32+ URL-safe символа [A-Za-z0-9_-]")
    hostname = props.get("AIDOCTOR_DOMAIN", "")
    if hostname != "localhost" and (
        len(hostname) > 253
        or "." not in hostname
        or not re.fullmatch(r"[a-z0-9.-]+", hostname)
        or hostname.startswith((".", "-"))
        or hostname.endswith((".", "-"))
        or ".." in hostname
    ):
        errors.append("AIDOCTOR_DOMAIN: ожидается localhost или собственное DNS-имя")
    binding = props.get("BIND_ADDRESS", "")
    if binding not in ("127.0.0.1", "0.0.0.0"):
        errors.append("BIND_ADDRESS: разрешены только 127.0.0.1 и 0.0.0.0")
    if binding == "0.0.0.0" and hostname == "localhost":
        errors.append("Публичная публикация с AIDOCTOR_DOMAIN=localhost запрещена")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка конфигурации DEPLOY-1")
    parser.add_argument(
        "filename",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".env.production",
    )
    args = parser.parse_args()
    errors = check_configuration(args.filename)
    if errors:
        for error in errors:
            print("ОШИБКА:", error)
        return 1
    print("Конфигурация DEPLOY-1: базовые ограничения соблюдены")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
