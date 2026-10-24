"""Миграции Alembic только для синтетической БД тестового VDS.

Пути определяются по расположению файла, а не по текущей директории
процесса; никаких внешних API или прямых действий с клиническими записями.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from alembic import command
from alembic.config import Config


def validate_environment(environment: Mapping[str, str]) -> None:
    """Защита от миграции локальной или production-БД."""
    url = environment.get("DATABASE_URL", "")
    parts = urlsplit(url)
    if (
        environment.get("APP_ENV") != "test"
        or parts.scheme != "postgresql+psycopg"
        or parts.hostname != "postgres"
        or parts.port != 5432
        or parts.path != "/aidoctor_synthetic"
    ):
        raise RuntimeError(
            "Миграция запрещена: требуется APP_ENV=test и "
            "postgresql+psycopg://...@postgres:5432/aidoctor_synthetic"
        )


def build_config(project_root: Path) -> Config:
    """Явно задаёт пути схемы и Python, независимо от cwd Alembic CLI."""
    root = project_root.resolve()
    ini = root / "alembic.ini"
    script_dir = root / "backend" / "alembic"
    backend = root / "backend"
    if not ini.is_file() or not (script_dir / "env.py").is_file():
        raise FileNotFoundError("Не найдены alembic.ini или backend/alembic/env.py")

    config = Config(str(ini))
    config.set_main_option("script_location", str(script_dir))
    config.set_main_option("prepend_sys_path", str(backend))
    return config


def main() -> None:
    validate_environment(os.environ)
    root = Path(__file__).resolve().parents[2]
    config = build_config(root)
    print("Alembic: использована проверенная конфигурация тестового VDS.")
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
