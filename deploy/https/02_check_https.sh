#!/usr/bin/env bash
# Повторяемый smoke-тест HTTPS без изменения данных.
set -Eeuo pipefail
root_dir="/opt/aidoctor"
repo="$root_dir/git-checkout"
env_https="$root_dir/https.env"

test -r "$env_https" || { echo "Не найден $env_https" >&2; exit 2; }
domain="$(sed -n 's/^AIDOCTOR_PUBLIC_DOMAIN=//p' "$env_https")"
test -n "$domain" || { echo "Не задан публичный домен." >&2; exit 2; }

cd "$repo"
dc=(
  docker compose
  --env-file "$repo/.env.test"
  --env-file "$env_https"
  -f "$repo/deploy/compose.test.yaml"
  -f "$repo/deploy/compose.https.yaml"
  --profile https
)

echo "=== Контейнеры ==="
"${dc[@]}" ps
echo "=== HTTPS ==="
code="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  --max-time 15 --resolve "$domain:443:127.0.0.1" "https://$domain/app")"
test "$code" = 200
echo "HTTPS $code: https://$domain/app"

echo "=== Скрытые служебные маршруты ==="
code="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  --max-time 15 --resolve "$domain:443:127.0.0.1" "https://$domain/docs")"
test "$code" = 404
echo "/docs: HTTP $code"

echo "=== Резервный локальный порт ==="
curl --fail --silent --show-error --max-time 8 \
  http://127.0.0.1:18080/api/v1/health | python3 -c '
import json, sys
data = json.load(sys.stdin)
assert data["status"] == "ok" and data["environment"] == "test", data
print("Локальный API: test/ok")
'

echo "=== Публичные порты контейнеров ==="
docker ps --format 'table {{.Names}}\t{{.Ports}}' | grep -E 'NAMES|aidoctor-vds-test'
echo "HTTPS подтверждён. PostgreSQL не должна иметь публикации 5432."
