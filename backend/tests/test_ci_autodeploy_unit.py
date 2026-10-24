"""Неиспользующая PostgreSQL проверка безопасности автодеплоя."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
module_file = ROOT / "deploy/ci/verify_compose.py"
spec = importlib.util.spec_from_file_location("aidoctor_verify_compose", module_file)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def valid_compose() -> dict:
    return {
        "name": "aidoctor-vds-test",
        "services": {
            "app": {
                "ports": [
                    {
                        "host_ip": "127.0.0.1",
                        "published": "18080",
                        "target": 8000,
                        "protocol": "tcp",
                    }
                ],
                "environment": {
                    "APP_ENV": "test",
                    "DATABASE_URL": (
                        "postgresql+psycopg://aidoctor:secret@postgres:5432/aidoctor_synthetic"
                    ),
                    "AIDOCTOR_ALLOW_SYNTHETIC_AI_DRAFTS": "0",
                },
                "volumes": [
                    {
                        "type": "volume",
                        "target": "/opt/aidoctor/data",
                        "source": "attachments_test",
                    }
                ],
            },
            "postgres": {
                "image": "postgres:16",
                "volumes": [
                    {
                        "type": "volume",
                        "target": "/var/lib/postgresql/data",
                        "source": "pg_synthetic",
                    }
                ],
            },
            "seed": {},
        },
        "volumes": {"pg_synthetic": {}, "attachments_test": {}},
    }


def test_valid_compose_is_accepted() -> None:
    module.validate(valid_compose())


@pytest.mark.parametrize(
    "change",
    [
        ("services", "app", "ports", 0, "host_ip", "0.0.0.0"),
        ("services", "app", "ports", 0, "published", "5432"),
        ("services", "postgres", "ports", [{"published": "5432"}]),
        ("services", "app", "environment", "APP_ENV", "production"),
        ("services", "app", "volumes", 0, "source", "attachments_other"),
    ],
)
def test_dangerous_change_is_rejected(change: tuple) -> None:
    cfg = deepcopy(valid_compose())
    *path, value = change
    obj = cfg
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value
    with pytest.raises(ValueError):
        module.validate(cfg)


def test_autodeploy_requires_server_guard() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "\n  autodeploy:\n" in ci
    assert "\n    needs: quality\n" in ci
    assert "VDS_AUTODEPLOY_ENABLED" in ci
    assert "refs/heads/master" in ci
    assert "StrictHostKeyChecking=yes" in ci
    assert "cancel-in-progress: false" in ci


def test_server_script_never_resets_database() -> None:
    script = (ROOT / "deploy/ci/server_autodeploy.sh").read_text(encoding="utf-8")
    assert "pg_dump" in script
    assert "run_vds_migrations.py" in script
    assert "python -m alembic -c alembic.ini upgrade head" not in script
    assert "down -v" not in script
    assert "seed_vds_synthetic" not in script
    assert "checkout --force --detach" in script
