#!/usr/bin/env bash
# Первый запуск HTTPS с доменом; не затрагивает БД, seed и SSH.
set -Eeuo pipefail
umask 077

if [[ "${EUID}" -ne 0 ]]; then
  echo "Нужны права root." >&2
  exit 2
fi
if [[ "$#" -ne 1 ]]; then
  echo "Использование: bash deploy/https/01_enable_https.sh имя.домена" >&2
  exit 2
fi

domain="${1,,}"
expected_ipv4="185.200.179.238"
root_dir="/opt/aidoctor"
repo="$root_dir/git-checkout"
env_https="$root_dir/https.env"

cd "$repo"
if [[ ! -s .env.test || ! -f deploy/compose.test.yaml || ! -f deploy/compose.https.yaml ]]; then
  echo "Не найдены файлы действующей тестовой среды в $repo" >&2
  exit 2
fi

# Никаких localhost, IP, wildcard и поддоменов в зоне, недоступной ACME.
python3 - "$domain" "$expected_ipv4" <<'PY'
import ipaddress
import re
import socket
import sys

domain, expected = sys.argv[1:]
labels = domain.split(".")
if (
    len(domain) > 253
    or len(labels) < 2
    or any(len(label) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) for label in labels)
    or labels[-1] in {"local", "localhost", "internal", "invalid", "test"}
):
    raise SystemExit("Ошибка: требуется публичный DNS-домен, например demo.ваш-домен.ru (латиницей).")
try:
    ipaddress.ip_address(domain)
except ValueError:
    pass
else:
    raise SystemExit("Ошибка: не используйте IP-адрес в качестве домена HTTPS.")

try:
    info = socket.getaddrinfo(domain, 443, type=socket.SOCK_STREAM)
except socket.gaierror as exc:
    raise SystemExit(f"DNS домена пока не разрешается: {exc}") from exc
addresses = {entry[4][0] for entry in info}
if addresses != {expected}:
    raise SystemExit(
        f"DNS должен указывать ТОЛЬКО на {expected}; сейчас получено: {sorted(addresses)}. "
        "Удалите ошибочные A/AAAA-записи и дождитесь обновления DNS."
    )
print(f"DNS проверен: {domain} -> {expected}")
PY

bash deploy/https/00_firewall.sh --check

# Не перехватывать чужой nginx/ispmanager, если Caddy ещё не запущен.
if ! docker ps --format '{{.Names}}' | grep -qx 'aidoctor-vds-test-proxy-1'; then
  occupied="$(ss -H -ltn | awk '{print $4}' | grep -E ':(80|443)$' || true)"
  if [[ -n "$occupied" ]]; then
    echo "Порты 80 или 443 уже заняты другим процессом: $occupied" >&2
    echo "Сначала выясните источник через: ss -lntp" >&2
    exit 3
  fi
fi

# .env тестового стенда не меняем; домен храним вне Git.
if [[ -f "$env_https" ]]; then
  saved="$(sed -n 's/^AIDOCTOR_PUBLIC_DOMAIN=//p' "$env_https")"
  if [[ "$saved" != "$domain" ]]; then
    echo "Уже настроен другой домен ($saved). Автоматическую смену запрещаем." >&2
    exit 3
  fi
else
  printf 'AIDOCTOR_PUBLIC_DOMAIN=%s\n' "$domain" > "$env_https"
  chmod 600 "$env_https"
fi

dc=(
  docker compose
  --env-file "$repo/.env.test"
  --env-file "$env_https"
  -f "$repo/deploy/compose.test.yaml"
  -f "$repo/deploy/compose.https.yaml"
  --profile https
)
"${dc[@]}" config --quiet
"${dc[@]}" run --rm --no-deps --entrypoint caddy proxy adapt \
  --config /etc/caddy/Caddyfile --adapter caddyfile > /dev/null

# Стандартная копия app/postgres остаётся той же: имя Compose-проекта не меняется.
"${dc[@]}" up -d --no-deps --force-recreate --wait --wait-timeout 120 proxy

echo "Проверяем выдачу сертификата и ответ приложения..."
ok=0
for _ in $(seq 1 24); do
  status="$(curl --silent --show-error --output /dev/null \
    --write-out '%{http_code}' --max-time 10 \
    --resolve "$domain:443:127.0.0.1" \
    "https://$domain/app" 2>/dev/null || true)"
  if [[ "$status" == "200" ]]; then
    ok=1
    break
  fi
  sleep 5
done
if [[ "$ok" != 1 ]]; then
  echo "HTTPS ещё не подтверждён. Логи Caddy:" >&2
  "${dc[@]}" logs --tail=70 proxy >&2
  "${dc[@]}" stop proxy || true
  echo "Публичный прокси остановлен; БД и FastAPI не затронуты." >&2
  echo "Проверьте DNS и доступность 80/443." >&2
  exit 4
fi

echo "УСПЕХ: https://$domain/app"
echo "Прежний localhost:18080 и SSH-туннель оставлены для резервного доступа."
