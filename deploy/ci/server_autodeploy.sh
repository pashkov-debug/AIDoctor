#!/usr/bin/env bash
# Root-owned entrypoint: установить через bootstrap; не запускать прямо из git checkout.
set -Eeuo pipefail
umask 077

if [[ "${EUID}" -ne 0 || "$#" -ne 1 || ! "$1" =~ ^[0-9a-f]{40}$ ]]; then
  echo "Требуется root и один валидный SHA-1 коммита." >&2
  exit 2
fi

commit="$1"
root_dir="/opt/aidoctor"
repo="$root_dir/git-checkout"
backups="$root_dir/backups"
env_file="$repo/.env.test"
lock="/run/lock/aidoctor-autodeploy.lock"

exec 9>"$lock"
flock -w 600 9 || { echo "Другой деплой всё ещё работает." >&2; exit 3; }

test -d "$repo/.git" && test -f "$env_file" || {
  echo "Не проведена начальная настройка или отсутствует .env.test." >&2
  exit 4
}
[[ "$(git -C "$repo" remote get-url origin)" == "https://github.com/pashkov-debug/AIDoctor.git" ]] || {
  echo "Неожиданный Git remote, прекращаем запуск." >&2
  exit 4
}
if [[ -n "$(git -C "$repo" status --porcelain --untracked-files=normal)" ]]; then
  echo "В Git checkout есть локальные изменения. Автодеплой остановлен." >&2
  exit 4
fi

git -C "$repo" fetch --no-tags --prune origin master
remote_head="$(git -C "$repo" rev-parse refs/remotes/origin/master)"
if [[ "$commit" != "$remote_head" ]]; then
  echo "Коммит $commit уже не является вершиной master; старый деплой пропущен."
  exit 0
fi

old_sha="$(git -C "$repo" rev-parse HEAD)"
if [[ "$old_sha" == "$commit" ]] && [[ -f "$root_dir/last_deployed_sha" ]] &&
   [[ "$(cat "$root_dir/last_deployed_sha")" == "$commit" ]]; then
  echo "Коммит уже развёрнут: $commit"
  exit 0
fi

test -f "$repo/deploy/compose.test.yaml" || {
  echo "Отсутствует конфигурация Compose в checkout." >&2
  exit 4
}
test "$(stat -c %a "$env_file")" = 600 || {
  echo "Неверные права секретов .env.test." >&2
  exit 4
}

docker compose --env-file "$env_file" -f "$repo/deploy/compose.test.yaml" ps -q postgres >/dev/null
dc=(docker compose --env-file "$env_file" -f "$repo/deploy/compose.test.yaml")
test -n "$("${dc[@]}" ps -q postgres)" || {
  echo "Нет работающего контейнера тестовой PostgreSQL." >&2
  exit 4
}
docker volume inspect aidoctor-vds-test_pg_synthetic >/dev/null 2>&1 || {
  echo "Защищаемый Docker-том PostgreSQL не найден." >&2
  exit 4
}

mkdir -p "$backups"
chmod 700 "$backups"
backup_file="$backups/aidoctor_synthetic_$(date -u +%Y%m%dT%H%M%SZ)_${commit:0:12}.dump"
temp_file="$backup_file.partial"
trap 'rm -f "$temp_file"' EXIT

echo "Резервная копия перед обновлением: $backup_file"
"${dc[@]}" exec -T postgres pg_dump -U aidoctor -d aidoctor_synthetic -Fc > "$temp_file"
test -s "$temp_file" || { echo "Пустая резервная копия, остановка." >&2; exit 5; }
mv -- "$temp_file" "$backup_file"
chmod 600 "$backup_file"

old_image_exists=0
rollback_tag="aidoctor:rollback-${old_sha:0:12}"
if docker image inspect aidoctor:vds-test >/dev/null 2>&1; then
  docker image tag aidoctor:vds-test "$rollback_tag"
  old_image_exists=1
fi

# Метка операции помогает установить причину без вывода секретов из окружения.
stage="Подготовка развёртывания"
rollback() {
  local rc=$?
  trap - ERR
  echo "ОШИБКА АВТОДЕПЛОЯ: этап «$stage», код $rc." >&2
  echo "Возврат к предыдущему приложению ${old_sha:0:12}." >&2
  if ! git -C "$repo" checkout --force --detach "$old_sha"; then
    echo "КРИТИЧНО: не удалось восстановить Git checkout!" >&2
  fi
  if [[ "$old_image_exists" -eq 1 ]]; then
    if ! docker image tag "$rollback_tag" aidoctor:vds-test; then
      echo "КРИТИЧНО: не удалось восстановить Docker image!" >&2
    elif ! timeout --kill-after=5s 150s "${dc[@]}" up -d --no-deps --wait --wait-timeout 120 app; then
      echo "КРИТИЧНО: прежний контейнер не восстановился автоматически!" >&2
    else
      echo "ОТКАТ: прежний Docker-контейнер запущен."
    fi
  else
    echo "ВНИМАНИЕ: образ прежней версии отсутствовал, автоматический откат образа невозможен." >&2
  fi
  echo "Версия checkout после попытки отката: $(git -C "$repo" rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "ВНИМАНИЕ: миграции БД автоматически НЕ откатываются." >&2
  echo "Резервная копия: $backup_file" >&2
  exit "$rc"
}
trap rollback ERR


stage="Checkout нового коммита"
git -C "$repo" checkout --force --detach "$commit"
cd "$repo"

stage="Проверка конфигурации Docker Compose"
"${dc[@]}" config --format json | python3 /usr/local/libexec/aidoctor-verify-compose
"${dc[@]}" config --quiet

# Никогда не пересоздаём данные с помощью seed во время деплоя.
stage="Сборка Docker"
"${dc[@]}" build app

stage="Миграция PostgreSQL"
"${dc[@]}" run --rm --no-deps --workdir /opt/aidoctor app \
  python /opt/aidoctor/backend/scripts/run_vds_migrations.py

stage="Запуск FastAPI"
"${dc[@]}" up -d --no-deps --wait --wait-timeout 120 app

stage="HTTP API /api/v1/health"
echo "POSTCHECK: $stage"
health_ok=0
for attempt in 1 2 3 4 5; do
  if health_json="$(curl --fail --silent --show-error --max-time 5 \
      http://127.0.0.1:18080/api/v1/health)" && \
     python3 -c '
import json
import sys
try:
    value = json.load(sys.stdin)
except ValueError:
    raise SystemExit("Health вернул некорректный JSON")
if value.get("status") != "ok" or value.get("environment") != "test":
    raise SystemExit("Health: ожидаются status=ok и environment=test")
' <<< "$health_json"; then
    health_ok=1
    break
  fi
  echo "POSTCHECK: /health попытка $attempt/5 не прошла"
  if [[ "$attempt" -lt 5 ]]; then sleep 2; fi
done
if [[ "$health_ok" -ne 1 ]]; then
  echo "POSTCHECK FAIL: /health не подтвердил status=ok, environment=test." >&2
  false
fi
echo "POSTCHECK OK: /api/v1/health"

stage="HTTP страница /app"
echo "POSTCHECK: $stage"
app_status=""
for attempt in 1 2 3 4 5; do
  if app_status="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
      --max-time 5 http://127.0.0.1:18080/app)" && \
      [[ "$app_status" == "200" ]]; then
    break
  fi
  echo "POSTCHECK: /app попытка $attempt/5, HTTP ${app_status:-нет ответа}"
  if [[ "$attempt" -lt 5 ]]; then sleep 2; fi
done
echo "POSTCHECK: /app HTTP ${app_status:-нет ответа}"
if [[ "$app_status" != "200" ]]; then
  echo "POSTCHECK FAIL: /app вернул HTTP ${app_status:-нет ответа} вместо 200." >&2
  false
fi
echo "POSTCHECK OK: /app"

# Ограничиваем время запросов к PostgreSQL, чтобы Actions не висел бесконечно.
db_scalar() {
  local value
  if ! value="$(timeout --kill-after=3s 25s "${dc[@]}" exec -T postgres \
      psql -X -v ON_ERROR_STOP=1 -U aidoctor -d aidoctor_synthetic -At -c "$1")"; then
    echo "POSTCHECK FAIL: PostgreSQL не ответила вовремя или запрос завершился ошибкой." >&2
    return 1
  fi
  printf '%s' "$value"
}

stage="Инвариант клинических черновиков"
echo "POSTCHECK: $stage"
draft_leaks="$(db_scalar "SELECT count(*) FROM clinical_orders WHERE source_reference LIKE 'synthetic:ui5:v1:candidate:%' AND status <> 'draft';")"
echo "POSTCHECK: утверждённых учебных черновиков-кандидатов: $draft_leaks"
if [[ "$draft_leaks" != "0" ]]; then
  echo "Нарушен инвариант: учебные черновики-кандидаты не должны быть утверждёнными." >&2
  false
fi
echo "POSTCHECK OK: клинические черновики"

stage="Количество синтетических пациентов"
echo "POSTCHECK: $stage"
patient_count="$(db_scalar "SELECT count(*) FROM patients WHERE demographics_json ->> 'synthetic' = 'true';")"
echo "POSTCHECK: синтетических пациентов $patient_count (минимум 3)"
if [[ ! "$patient_count" =~ ^[0-9]+$ ]] || (( patient_count < 3 )); then
  echo "Проверка синтетических пациентов: ожидалось >= 3, получено '$patient_count'." >&2
  false
fi
echo "POSTCHECK OK: пациенты"

trap - ERR
printf '%s\n' "$commit" > "$root_dir/last_deployed_sha"
chmod 600 "$root_dir/last_deployed_sha"
if [[ "$old_image_exists" -eq 1 ]]; then docker image rm "$rollback_tag" >/dev/null || true; fi
echo "АВТОДЕПЛОЙ УСПЕШЕН: $commit"
echo "База данных и вложения сохранены. Внешние HTTP-порты не открывались."
