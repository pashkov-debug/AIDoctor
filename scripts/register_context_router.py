"""Безопасное включение маршрута без замены локального backend/app/main.py.

Запускать из корня репозитория: python scripts/register_context_router.py
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "backend" / "app" / "main.py"
IMPORT = "from app.api.routes.context import router as context_router"
ENTRY_RE = re.compile(r"^([ \t]*)history_events_router,[ \t]*$", re.MULTILINE)


def main() -> None:
    if not MAIN.is_file():
        raise SystemExit(f"Отсутствует {MAIN}")
    source = MAIN.read_text(encoding="utf-8")
    already_imported = IMPORT in source
    already_mounted = bool(re.search(r"^[ \t]*context_router,[ \t]*$", source, re.MULTILINE))

    if already_imported and already_mounted:
        print("Маршрут context уже подключён; без изменений.")
        return
    if already_imported != already_mounted:
        raise SystemExit("Маршрут подключён частично; требуется ручная проверка main.py")

    anchor = "from app.core.config import settings"
    if source.count(anchor) != 1:
        raise SystemExit("Не найдена однозначная позиция импорта в main.py")
    matches = list(ENTRY_RE.finditer(source))
    if len(matches) != 1:
        raise SystemExit("Не найдена однозначная позиция history_events_router в main.py")

    source = source.replace(anchor, f"{IMPORT}\n{anchor}", 1)
    match = ENTRY_RE.search(source)
    if match is None:
        raise SystemExit("Не удалось найти регистрацию history_events_router")
    indent = match.group(1)
    pos = match.end()
    source = source[:pos] + f"\n{indent}context_router," + source[pos:]
    ast.parse(source, filename=str(MAIN))

    # Никаких затрагиваний attachments_router и прочих локальных правок.
    backup = MAIN.with_suffix(".py.context-backup")
    if backup.exists():
        raise SystemExit(f"Резервная копия уже существует: {backup}")
    backup.write_text(MAIN.read_text(encoding="utf-8"), encoding="utf-8")
    MAIN.write_text(source, encoding="utf-8")
    print(f"Подключён context_router. Резервная копия: {backup}")


if __name__ == "__main__":
    main()
