#!/usr/bin/env bash
# Аудит / ограничение UFW для выделенного VDS AIDoctor.
# --apply удаляет ТОЛЬКО известные предустановленные правила почты, FTP, DNS, ispmanager.
set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Требуются права root." >&2
  exit 2
fi
if ! ufw status | grep -q '^Status: active'; then
  echo "UFW должен быть активен; автоматическое включение отклонено." >&2
  exit 2
fi

check_allowlist() {
  ufw status | python3 -c '
import sys
allowed = {"22/tcp", "80/tcp", "443/tcp"}
invalid = []
for line in sys.stdin:
    if "ALLOW" not in line or "ALLOW OUT" in line:
        continue
    target = line.split("ALLOW", 1)[0].strip()
    target = target.replace(" (v6)", "").strip()
    if target not in allowed:
        invalid.append(target)
if invalid:
    print("Лишние разрешающие правила UFW: " + ", ".join(sorted(set(invalid))), file=sys.stderr)
    sys.exit(1)
print("UFW: только SSH (22/tcp), HTTP (80/tcp), HTTPS (443/tcp).")
'
}

if [[ "${1:-}" == "--check" ]]; then
  check_allowlist
  exit
fi

echo "=== Текущие правила UFW ==="
ufw status
echo "=== Слушающие процессы (контроль перед блокировкой портов) ==="
ss -lntup || true

if [[ "${1:-}" != "--apply" ]]; then
  echo "Это просмотр, правила не изменены."
  echo "Если VDS выделен только под AIDoctor и другие службы не используются:"
  echo "  bash deploy/https/00_firewall.sh --apply"
  exit 0
fi

echo "ВНИМАНИЕ: портами почты, FTP, DNS и ispmanager снаружи пользоваться будет нельзя."
echo "SSH 22/tcp будет сохранён; действующий терминал не отключаем."
ufw allow 22/tcp comment "AIDoctor SSH"
ufw allow 80/tcp comment "AIDoctor HTTPS issuance"
ufw --force delete allow 443 >/dev/null 2>&1 || true
ufw allow 443/tcp comment "AIDoctor HTTPS"

for rule in \
  ispmanager \
  21/tcp 110/tcp 143/tcp 993/tcp 995/tcp \
  25/tcp 465/tcp 587/tcp \
  53/tcp 53/udp \
  1500/tcp 1501/tcp '1500,1501/tcp'
do
  ufw --force delete allow "$rule" >/dev/null 2>&1 || true
done

echo "=== Правила после ограничения ==="
ufw status
check_allowlist
