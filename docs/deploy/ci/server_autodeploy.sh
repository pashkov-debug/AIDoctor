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

rollback() {
  local rc=$?
  trap - ERR
  echo "ОШИБКА деплоя ($rc). Восстанавливаем предыдущую версию приложения." >&2
  git -C "$repo" checkout --force --detach "$old_sha" || true
  if [[ "$old_image_exists" -eq 1 ]]; then
    docker image tag "$rollback_tag" aidoctor:vds-test || true
    "${dc[@]}" up -d --no-deps --wait --wait-timeout 120 app || true
  fi
  echo "ВНИМАНИЕ: миграции БД автоматически НЕ откатываются." >&2
  echo "Резервная копия: $backup_file" >&2
  exit "$rc"
}
trap rollback ERR

git -C "$repo" checkout --force --detach "$commit"
cd "$repo"
"${dc[@]}" config --format json | python3 /usr/local/libexec/aidoctor-verify-compose
"${dc[@]}" config --quiet

# Никакого повторного seed: аккаунты, карточки и проекты лекарств сохраняются.
"${dc[@]}" build app
"${dc[@]}" run --rm --no-deps app python -m alembic -c alembic.ini upgrade head
"${dc[@]}" up -d --no-deps --wait --wait-timeout 120 app

curl --fail --silent --show-error --max-time 12 \
  "http://127.0.0.1:18080/api/v1/health" |
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("status")=="ok" and d.get("environment")=="test", d'
test "$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --max-time 12 http://127.0.0.1:18080/app)" = 200

# Инвариант: синтетические проекты не становятся назначениями.
draft_leaks="$("${dc[@]}" exec -T postgres psql -U aidoctor -d aidoctor_synthetic -At \
  -c "SELECT count(*) FROM clinical_orders WHERE source_reference LIKE 'synthetic:ui5:v1:candidate:%' AND status <> 'draft';")"
test "$draft_leaks" = 0
patient_count="$("${dc[@]}" exec -T postgres psql -U aidoctor -d aidoctor_synthetic -At \
  -c "SELECT count(*) FROM patients WHERE demographics_json ->> 'synthetic' = 'true';")"
test "$patient_count" = 3

trap - ERR
printf '%s\n' "$commit" > "$root_dir/last_deployed_sha"
chmod 600 "$root_dir/last_deployed_sha"
if [[ "$old_image_exists" -eq 1 ]]; then docker image rm "$rollback_tag" >/dev/null || true; fi
echo "АВТОДЕПЛОЙ УСПЕШЕН: $commit"
echo "База данных и вложения сохранены. Внешние HTTP-порты не открывались."
