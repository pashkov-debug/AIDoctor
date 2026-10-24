"""Регрессия политики CI: лёгкий push и ручные БД-тесты."""

import re
from pathlib import Path

CI = (
    Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
).read_text(encoding="utf-8")


def _job(name: str) -> str:
    """Возвращает секцию задания по двум пробелам корневого уровня jobs."""
    marker = f"  {name}:\n"
    assert CI.count(marker) == 1
    return re.split(
        r"\n(?=  [a-z][a-z0-9_]*:\n)", CI.split(marker, 1)[1], maxsplit=1
    )[0]


def test_push_checks_do_not_touch_postgresql_or_run_pytest():
    quality = _job("quality")
    assert "python -m ruff check backend" in quality
    assert "python -m ruff format --check backend" in quality
    assert "node --check backend/app/web/assets/app.js" in quality
    assert "python -m compileall -q backend/app" in quality
    assert "postgres:" not in quality
    assert "python -m pytest" not in quality
    assert "python -m alembic" not in quality


def test_full_tests_are_manual_and_use_dedicated_test_db():
    full_tests = _job("full_tests")
    assert "workflow_dispatch:" in CI
    assert "if: github.event_name == 'workflow_dispatch'" in full_tests
    assert "image: postgres:16" in full_tests
    assert "CREATE DATABASE aidoctor_test" in full_tests
    assert "aidoctor_test" in full_tests
    assert "python -m alembic -c alembic.ini upgrade head" in full_tests
    assert "python -m pytest backend/tests -q -rs" in full_tests


def test_ci_has_no_automatic_production_deployment():
    assert "on:" in CI
    assert "deploy:" not in CI
    assert "docker push" not in CI
    assert "ssh root@" not in CI
