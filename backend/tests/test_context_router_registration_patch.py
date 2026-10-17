"""Smoke: подключение маршрута не стирает уже работающие роутеры."""

import subprocess
import sys
from pathlib import Path


def test_register_context_router_is_idempotent(tmp_path):
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts" / "register_context_router.py"
    (tmp_path / "scripts").mkdir()
    (tmp_path / "backend" / "app").mkdir(parents=True)
    target_script = tmp_path / "scripts" / script.name
    target_script.write_text(script.read_text(encoding="utf-8"), encoding="utf-8")
    main_file = tmp_path / "backend" / "app" / "main.py"
    original = (
        "from app.api.routes.attachments import router as attachments_router\n"
        "from app.core.config import settings\n"
        "routers = (\n"
        "    attachments_router,\n"
        "    history_events_router,\n"
        ")\n"
    )
    main_file.write_text(original, encoding="utf-8")

    first = subprocess.run(
        [sys.executable, str(target_script)],
        capture_output=True,
        text=True,
        check=False,
    )
    second = subprocess.run(
        [sys.executable, str(target_script)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == second.returncode == 0, (first.stderr, second.stderr)
    result = main_file.read_text(encoding="utf-8")
    assert result.count("    context_router,") == 1
    assert "    attachments_router," in result
    assert (main_file.with_suffix(".py.context-backup")).read_text(encoding="utf-8") == original
