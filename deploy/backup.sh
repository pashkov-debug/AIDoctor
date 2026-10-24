#!/bin/sh
# Снимок БД и вложений в каталог вне Git. НЕ заменяет проверку восстановления.
set -eu
umask 077

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -f .env.production ]; then
    echo "Отсутствует .env.production" >&2
    exit 1
fi

BACKUP_DIR="${AIDOCTOR_BACKUP_DIR:-$HOME/aidoctor-backups}"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="$BACKUP_DIR/$STAMP"
mkdir -m 700 "$DEST"
cleanup() {
    if [ ! -f "$DEST/SHA256SUMS" ]; then
        rm -f "$DEST/database.dump" "$DEST/attachments.tar.gz"
        rmdir "$DEST" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

docker compose --env-file .env.production -f deploy/compose.yaml exec -T postgres \
    pg_dump -U aidoctor -d aidoctor -Fc > "$DEST/database.dump"

docker compose --env-file .env.production -f deploy/compose.yaml exec -T app \
    python -c 'import sys, tarfile; t=tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz"); t.add("/opt/aidoctor/data/attachments", arcname="attachments"); t.close()' \
    > "$DEST/attachments.tar.gz"

(
    cd "$DEST"
    sha256sum database.dump attachments.tar.gz > SHA256SUMS
    sha256sum -c SHA256SUMS
)
echo "Создана копия: $DEST"
echo "Важно: перенесите файлы в зашифрованное независимое хранилище."
