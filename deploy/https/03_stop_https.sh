#!/usr/bin/env bash
# Экстренно закрывает публичный вход, не удаляя БД и TLS-сертификаты.
set -Eeuo pipefail

root_dir="/opt/aidoctor"
repo="$root_dir/git-checkout"
test -r "$root_dir/https.env" || {
  echo "HTTPS ещё не включён." >&2
  exit 2
}
cd "$repo"
docker compose \
  --env-file "$repo/.env.test" \
  --env-file "$root_dir/https.env" \
  -f "$repo/deploy/compose.test.yaml" \
  -f "$repo/deploy/compose.https.yaml" \
  --profile https \
  stop proxy
echo "Публичный Caddy остановлен; PostgreSQL, FastAPI и TLS-тома сохранены."
