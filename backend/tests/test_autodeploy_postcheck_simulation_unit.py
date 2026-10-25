"""Имитация post-deploy проверок без Docker и настоящей PostgreSQL.

Запускаем Bash-скрипт через stdin, без передачи Windows-путей вида C:\\... .
Передаём UTF-8 байты, чтобы Windows не преобразовывала LF в CRLF.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "deploy/ci/server_autodeploy.sh").read_text(encoding="utf-8")


def _run_postchecks(
    *, patients: str, leaks: str, app_status: str
) -> subprocess.CompletedProcess[str]:
    """Подставить ответы внешних команд и выполнить настоящие Bash-проверки."""
    if shutil.which("bash") is None:
        pytest.skip("Для Bash-проверок требуется bash (Linux, Git Bash или WSL)")

    start = SCRIPT.index('stage="HTTP API /api/v1/health"')
    end = SCRIPT.index("\ntrap - ERR\nprintf", start)
    postcheck_code = SCRIPT[start:end]

    runner = "\n".join(
        [
            "set -Eeuo pipefail",
            "trap 'echo FAILED_STAGE=$stage >&2; exit 1' ERR",
            # Значения ограничены цифрами — они не содержат shell-метасимволов.
            f"FAKE_PATIENTS={int(patients)}",
            f"FAKE_LEAKS={int(leaks)}",
            f"FAKE_APP_HTTP={int(app_status)}",
            "dc=(mock_compose)",
            # Вместо настоящего HTTP подставляем тело health и код /app.
            """curl() {
  case " $* " in
    *" --write-out "*) printf '%s' "$FAKE_APP_HTTP" ;;
    *) printf '%s\\n' '{"status":"ok","environment":"test"}' ;;
  esac
}""",
            # Проверяем успешную обработку известного корректного JSON.
            # Реальный разбор JSON проверяется отдельно в API-тестах.
            """python3() {
  local payload
  payload="$(cat)"
  [[ "$payload" == '{"status":"ok","environment":"test"}' ]]
}""",
            # Имитируем два SQL-запроса, не обращаясь к базе.
            """timeout() {
  case " $* " in
    *clinical_orders*) printf '%s\\n' "$FAKE_LEAKS" ;;
    *) printf '%s\\n' "$FAKE_PATIENTS" ;;
  esac
}""",
            "sleep() { :; }",
            postcheck_code,
            "",
        ]
    )

    # ВАЖНО: bytes input не подвергается преобразованию LF -> CRLF в Windows.
    result = subprocess.run(
        ["bash", "-s"],
        input=runner.encode("utf-8"),
        capture_output=True,
        timeout=20,
        check=False,
    )
    return subprocess.CompletedProcess(
        args=result.args,
        returncode=result.returncode,
        stdout=result.stdout.decode("utf-8", errors="replace"),
        stderr=result.stderr.decode("utf-8", errors="replace"),
    )


def test_postcheck_passes_for_four_patients() -> None:
    outcome = _run_postchecks(patients="4", leaks="0", app_status="200")
    assert outcome.returncode == 0, outcome.stderr
    assert "POSTCHECK OK: пациенты" in outcome.stdout


def test_postcheck_reports_draft_leaks() -> None:
    outcome = _run_postchecks(patients="4", leaks="2", app_status="200")
    assert outcome.returncode != 0
    assert "FAILED_STAGE=Инвариант клинических черновиков" in outcome.stderr


def test_postcheck_reports_patient_count() -> None:
    outcome = _run_postchecks(patients="2", leaks="0", app_status="200")
    assert outcome.returncode != 0
    assert "FAILED_STAGE=Количество синтетических пациентов" in outcome.stderr
