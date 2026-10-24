"""Регрессия CI: сохранность учебных формулировок и лимит строк Python."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    ROOT / "backend/scripts/seed_ui5_clinical_scenarios.py",
    ROOT / "backend/app/services/clinical_order.py",
)
EXPECTED_UI5_TEXTS = {
    "Со слов взрослого пациента: продолжает принимать фенелзин, "
    "схема и даты последнего приёма требуют сверки с назначением другого врача.",
    "Уточнить сопутствующие заболевания, лекарственную историю "
    "и переносимость ранее применявшихся препаратов.",
    "Со слов пациента появились мысли о причинении себе вреда. "
    "Требуется срочная оценка врачом; автоматических назначений нет.",
}
EXPECTED_GUARD_TEXT = (
    "Учебный проект назначения UI-5 запрещено утверждать. "
    "Создайте отдельное проверенное назначение."
)


def _string_literals(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_ui5_event_texts_preserved() -> None:
    assert EXPECTED_UI5_TEXTS <= _string_literals(FILES[0])


def test_ui5_approval_guard_message_preserved() -> None:
    assert EXPECTED_GUARD_TEXT in _string_literals(FILES[1])


def test_changed_python_files_have_no_lines_over_100() -> None:
    for path in FILES:
        over_limit = [
            index
            for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if len(line) > 100
        ]
        assert not over_limit, f"{path}: строки длиннее 100: {over_limit}"
