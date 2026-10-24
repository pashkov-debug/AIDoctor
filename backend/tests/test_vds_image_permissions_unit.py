"""Регрессия прав чтения исходников в тестовом Docker-образе VDS."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "deploy" / "Dockerfile.test"
COMPOSE = ROOT / "deploy" / "compose.test.yaml"


def test_code_becomes_readable_after_copy_before_nonroot_user() -> None:
    content = DOCKERFILE.read_text(encoding="utf-8")
    copy_scripts = content.index("COPY backend/scripts ./backend/scripts")
    copy_ini = content.index("COPY alembic.ini ./")
    permissions = content.index("RUN chmod -R a+rX /opt/aidoctor/backend /opt/aidoctor/alembic.ini")
    nonroot_user = content.index("USER 10001:10001")

    assert copy_scripts < permissions
    assert copy_ini < permissions < nonroot_user


def test_container_remains_nonroot_and_read_only() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    compose = COMPOSE.read_text(encoding="utf-8")

    assert "USER 10001:10001" in dockerfile
    assert "read_only: true" in compose
    assert "127.0.0.1:18080:8000" in compose
