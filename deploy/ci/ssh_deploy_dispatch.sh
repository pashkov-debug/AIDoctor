#!/usr/bin/env bash
# Выполняется только для отдельного SSH-ключа GitHub Actions.
set -Eeuo pipefail

original="${SSH_ORIGINAL_COMMAND:-}"
if [[ ! "$original" =~ ^deploy[[:space:]]([0-9a-f]{40})$ ]]; then
  echo "Отказ: разрешена только команда deploy с SHA-1 коммита." >&2
  exit 2
fi

exec sudo -n /usr/local/sbin/aidoctor-autodeploy "${BASH_REMATCH[1]}"
