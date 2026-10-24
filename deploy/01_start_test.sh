#!/usr/bin/env bash
# Запуск без удаления БД; только выделенная тестовая среда AIDoctor.
set -Eeuo pipefail

cd "$(dirname "$0")/.."
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "ОШИБКА: сначала установите Docker Engine и Compose Plugin." >&2
  exit 1
fi
if [ ! -f backend/app/core/config.py ] || [ ! -f backend/scripts/seed_ui5_clinical_scenarios.py ] || [ ! -f alembic.ini ]; then
  echo "ОШИБКА: неполный исходный проект AIDoctor. Нужен архив владельца." >&2
  exit 1
fi
if [ ! -f backend/scripts/seed_vds_synthetic.py ]; then
  echo "ОШИБКА: не найден серверный seed. Наложите ZIP в корень AIDoctor." >&2
  exit 1
fi

umask 077
if [ ! -e .env.test ]; then
  echo "Создаём уникальные секреты для закрытого тестового сервера."
  python3 - <<'PY'
from pathlib import Path
import secrets

fields = ("DB_PASSWORD", "DEMO_DOCTOR_PASSWORD",
          "DEMO_PATIENT_PASSWORD", "DEMO_ADMIN_PASSWORD")
path = Path(".env.test")
with path.open("x", encoding="utf-8") as file:
    for field in fields:
        file.write(f"{field}={secrets.token_urlsafe(36)}\n")
PY
else
  echo "Существующий .env.test сохранён без изменений."
fi

chmod 600 .env.test
python3 - <<'PY'
import re
from pathlib import Path

p = Path(".env.test")
if p.stat().st_mode & 0o077:
    raise SystemExit("Ошибка: права .env.test должны быть 0600")
entries = {}
for line in p.read_text(encoding="utf-8").splitlines():
    if not line.strip() or line.startswith("#"):
        continue
    k, delim, v = line.partition("=")
    if not delim or k in entries:
        raise SystemExit("Ошибка формата .env.test")
    entries[k] = v
required = ("DB_PASSWORD", "DEMO_DOCTOR_PASSWORD",
            "DEMO_PATIENT_PASSWORD", "DEMO_ADMIN_PASSWORD")
if any(not re.fullmatch(r"[a-zA-Z0-9_-]{32,}", entries.get(k, "")) for k in required):
    raise SystemExit("Ошибка: нужны случайные URL-safe пароли >=32 символов")
if len({entries[k] for k in required}) != len(required):
    raise SystemExit("Ошибка: пароли должны отличаться")
print("Настройки и секреты прошли локальную проверку.")
PY

dc=(docker compose --env-file .env.test -f deploy/compose.test.yaml)
"${dc[@]}" config --quiet
"${dc[@]}" build app
"${dc[@]}" up -d --wait postgres
"${dc[@]}" run --rm --no-deps --workdir /opt/aidoctor app \
  python /opt/aidoctor/backend/scripts/run_vds_migrations.py
"${dc[@]}" run --rm seed
"${dc[@]}" up -d --wait app

echo "Готово: порт HTTP доступен только внутри VDS на 127.0.0.1:18080."
echo "Для проверки запустите: bash deploy/02_check_test.sh"
echo "Для Windows: ssh -N -L 18080:127.0.0.1:18080 root@185.200.179.238"
echo "Затем на Windows откройте: http://127.0.0.1:18080/app"
