"""Не требуют БД: запрет подмены цели и структура серверных файлов."""

import ast
from pathlib import Path

import pytest

from backend.scripts.seed_vds_synthetic import require_safe_target

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("environment", "url", "actual"),
    [
        (
            "test",
            "postgresql+psycopg://aidoctor:pw@postgres:5432/aidoctor_synthetic",
            "aidoctor_synthetic",
        ),
    ],
)
def test_allow_dedicated_target(environment: str, url: str, actual: str) -> None:
    require_safe_target(environment, url, actual)


@pytest.mark.parametrize(
    ("environment", "url", "actual"),
    [
        (
            "production",
            "postgresql+psycopg://aidoctor:p@postgres/aidoctor_synthetic",
            "aidoctor_synthetic",
        ),
        (
            "local",
            "postgresql+psycopg://aidoctor:p@postgres/aidoctor_synthetic",
            "aidoctor_synthetic",
        ),
        ("test", "postgresql+psycopg://aidoctor:p@postgres/aidoctor", "aidoctor"),
        (
            "test",
            "postgresql+psycopg://aidoctor:p@127.0.0.1/aidoctor_synthetic",
            "aidoctor_synthetic",
        ),
        ("test", "postgresql+psycopg://aidoctor:p@postgres/aidoctor_synthetic", "other_database"),
    ],
)
def test_reject_unsafe_target(environment: str, url: str, actual: str) -> None:
    with pytest.raises(ValueError, match="отдельная"):
        require_safe_target(environment, url, actual)


def test_local_seed_guards_unchanged() -> None:
    scripts = [
        ROOT / "backend/scripts/seed_ui2a_synthetic.py",
        ROOT / "backend/scripts/seed_ui2b_synthetic.py",
        ROOT / "backend/scripts/seed_ui5_clinical_scenarios.py",
    ]
    for path in scripts:
        assert path.exists()
        assert "ensure_local_development_target" in path.read_text(encoding="utf-8")


def test_scripts_parse() -> None:
    for relative in [
        "backend/scripts/seed_vds_synthetic.py",
        "deploy/01_start_test.sh",
    ]:
        path = ROOT / relative
        assert path.exists()
    ast.parse((ROOT / "backend/scripts/seed_vds_synthetic.py").read_text(encoding="utf-8"))
