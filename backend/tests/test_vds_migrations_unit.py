"""Регрессия путей Alembic и запрета миграции чужой БД."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "backend" / "scripts" / "run_vds_migrations.py"
spec = importlib.util.spec_from_file_location("aidoctor_vds_migrations", MODULE_PATH)
assert spec is not None and spec.loader is not None
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def test_alembic_resolves_paths_outside_project_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    config = migration.build_config(ROOT)
    assert Path(config.get_main_option("script_location")) == ROOT / "backend" / "alembic"
    assert Path(config.get_main_option("prepend_sys_path")) == ROOT / "backend"


def test_invalid_config_layout_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        migration.build_config(tmp_path)


@pytest.mark.parametrize(
    "overrides",
    [
        {"APP_ENV": "production"},
        {"DATABASE_URL": "postgresql+psycopg://u:p@127.0.0.1:5432/aidoctor_synthetic"},
        {"DATABASE_URL": "postgresql+psycopg://u:p@postgres:5432/aidoctor"},
        {"DATABASE_URL": "postgresql+psycopg://u:p@postgres:5433/aidoctor_synthetic"},
        {"DATABASE_URL": "sqlite:///test.db"},
    ],
)
def test_migrations_refuse_non_synthetic_database(overrides: dict[str, str]) -> None:
    env = {
        "APP_ENV": "test",
        "DATABASE_URL": (
            "postgresql+psycopg://aidoctor:synthetic@postgres:5432/"
            "aidoctor_synthetic"
        ),
    }
    env.update(overrides)
    with pytest.raises(RuntimeError, match="Миграция запрещена"):
        migration.validate_environment(env)


def test_synthetic_database_is_accepted() -> None:
    migration.validate_environment(
        {
            "APP_ENV": "test",
            "DATABASE_URL": (
                "postgresql+psycopg://aidoctor:synthetic@postgres:5432/"
                "aidoctor_synthetic"
            ),
        }
    )


def test_both_deployment_scripts_use_safe_migration_runner() -> None:
    for path in (
        ROOT / "deploy" / "ci" / "server_autodeploy.sh",
        ROOT / "deploy" / "01_start_test.sh",
    ):
        text = path.read_text(encoding="utf-8")
        assert "python /opt/aidoctor/backend/scripts/run_vds_migrations.py" in text
        assert "--workdir /opt/aidoctor" in text
