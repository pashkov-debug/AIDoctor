#!/usr/bin/env python3
"""Сверка ручного отката AIDoctor с этапом 6.6 FINAL. Ничего не изменяет."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit(root: Path, reference: dict) -> dict:
    missing: list[str] = []
    changed: list[str] = []
    matched = 0

    for entry in reference["files"]:
        relative = entry["path"]
        file_path = root / Path(relative)
        if not file_path.is_file():
            missing.append(relative)
        elif file_sha256(file_path) != entry["sha256"]:
            changed.append(relative)
        else:
            matched += 1

    remnants = [name for name in reference["temporary_paths"] if (root / name).exists()]
    config_notes = []
    env_example = root / ".env.example"
    if not env_example.is_file():
        config_notes.append("Отсутствует .env.example — нужен для документирования настроек.")
    else:
        content = env_example.read_text(encoding="utf-8-sig", errors="replace")
        for keyword in ("AIDOCTOR_DEMO", "AIDOCTOR_LIVE", "MCP_PUBLIC_HOST"):
            if keyword in content:
                config_notes.append(
                    f".env.example содержит {keyword}: убедись, что это не забытая демо-настройка."
                )

    readme = root / "README.md"
    if not readme.is_file():
        config_notes.append("Отсутствует README.md.")
    else:
        readme_content = readme.read_text(encoding="utf-8-sig", errors="replace")
        for word in ("Demo Bridge", "Live Demo", "ngrok"):
            if word.casefold() in readme_content.casefold():
                config_notes.append(f"README.md всё ещё упоминает «{word}»: проверь актуальность.")
    return {
        "reference": reference["reference"],
        "root": str(root),
        "expected": len(reference["files"]),
        "matched": matched,
        "missing": missing,
        "changed": changed,
        "temporary_remnants": remnants,
        "configuration_notes": config_notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Неизменяющая проверка отката временных мостов AIDoctor."
    )
    parser.add_argument(
        "project_root", nargs="?", default=".", help="Каталог AIDoctor (по умолчанию текущий)."
    )
    parser.add_argument(
        "--report", metavar="PATH",
        help="Необязательно: сохранить JSON-отчёт. В нём только пути и итоги, без секретов."
    )
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    ref_path = Path(__file__).with_name("stage6_final_reference.json")
    if not (root / "backend" / "app").is_dir():
        print(f"Ошибка: {root} не похож на корень AIDoctor.", file=sys.stderr)
        return 2
    reference = json.loads(ref_path.read_text(encoding="utf-8"))
    result = audit(root, reference)
    print("=== AIDoctor / Сверка отката до 6.6 FINAL ===")
    print("Эталон:", result["reference"])
    print("Проверено:", result["expected"])
    print("Совпало:", result["matched"])
    for key, title in (
        ("missing", "ОТСУТСТВУЮТ (требуется разобраться)"),
        ("changed", "ОТЛИЧАЮТСЯ (не обязательно ошибка)"),
        ("temporary_remnants", "ОСТАТКИ ВРЕМЕННОЙ ИНТЕГРАЦИИ"),
        ("configuration_notes", "НАСТРОЙКИ / ДОКУМЕНТАЦИЯ"),
    ):
        values = result[key]
        print(f"\n{title}: {len(values)}")
        for value in values:
            print(" -", value)

    if args.report:
        destination = Path(args.report).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print("\nОтчёт записан:", destination)

    if result["missing"]:
        print("\nИТОГ: НЕ ГОТОВО. Есть отсутствующие файлы контрольного этапа.")
        return 1
    if result["changed"] or result["temporary_remnants"] or result["configuration_notes"]:
        print("\nИТОГ: ТРЕБУЕТ ПРОСМОТРА. Без автоматического удаления или замены.")
        return 0
    print("\nИТОГ: Контрольный набор совпал. Нужны Ruff / Alembic / pytest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
