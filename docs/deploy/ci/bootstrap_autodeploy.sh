#!/usr/bin/env bash
# Первичная настройка — запустить один раз от root на FirstVDS после публикации файлов в master.
set -Eeuo pipefail
umask 077

if [[ "$EUID" -ne 0 ]]; then
  echo "Требуются права root." >&2
  exit 2
fi

host_dir="/opt/aidoctor"
legacy="$host_dir/AIDoctor"
repo="$host_dir/git-checkout"
pub="/root/aidoctor_actions_deploy.pub"
for file in "$pub" /root/server_autodeploy.sh /root/ssh_deploy_dispatch.sh /root/verify_compose.py; do
  test -s "$file" || { echo "Не найден $file" >&2; exit 3; }
done
test -f "$legacy/.env.test" || {
  echo "Не найдены секреты работающего тестового AIDoctor: $legacy/.env.test" >&2
  exit 3
}
test "$(stat -c '%a' "$legacy/.env.test")" = 600 || {
  echo "Права исходного .env.test должны быть 0600" >&2; exit 3
}
ssh-keygen -l -f "$pub" >/dev/null
read -r key_type key_data _ < "$pub"
[[ "$key_type" == "ssh-ed25519" && "$key_data" =~ ^[A-Za-z0-9+/=]+$ ]] || {
  echo "Ожидается публичный ключ ssh-ed25519" >&2
  exit 3
}
systemctl is-active --quiet docker
docker compose version >/dev/null

# Новый checkout отдельно от ZIP-развёртывания; прежнюю папку и Docker-тома не трогаем.
if [[ ! -e "$repo" ]]; then
  git clone --single-branch --branch master \
    https://github.com/pashkov-debug/AIDoctor.git "$repo"
fi
test -d "$repo/.git"
[[ "$(git -C "$repo" remote get-url origin)" == "https://github.com/pashkov-debug/AIDoctor.git" ]]
test -f "$repo/deploy/compose.test.yaml" || {
  echo "В GitHub master пока нет deploy/compose.test.yaml. Сначала отправьте инкремент в GitHub." >&2
  exit 3
}
if [[ ! -e "$repo/.env.test" ]]; then
  install -m 600 -o root -g root "$legacy/.env.test" "$repo/.env.test"
fi
test "$(stat -c '%a' "$repo/.env.test")" = 600

# Защищённый путь sudo и белый список единственной SSH-команды.
install -d -m 755 /usr/local/libexec
install -m 755 -o root -g root /root/server_autodeploy.sh /usr/local/sbin/aidoctor-autodeploy
install -m 755 -o root -g root /root/ssh_deploy_dispatch.sh /usr/local/libexec/aidoctor-deploy-dispatch
install -m 755 -o root -g root /root/verify_compose.py /usr/local/libexec/aidoctor-verify-compose

if ! id -u aidoctor-deploy >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash aidoctor-deploy
  passwd -l aidoctor-deploy >/dev/null
fi
install -d -m 700 -o aidoctor-deploy -g aidoctor-deploy /home/aidoctor-deploy/.ssh
printf 'restrict,command="/usr/local/libexec/aidoctor-deploy-dispatch" %s %s aidoctor-ci\n' \
    "$key_type" "$key_data" > /home/aidoctor-deploy/.ssh/authorized_keys
chown aidoctor-deploy:aidoctor-deploy /home/aidoctor-deploy/.ssh/authorized_keys
chmod 600 /home/aidoctor-deploy/.ssh/authorized_keys

sudoers="/etc/sudoers.d/aidoctor-autodeploy"
cat > "$sudoers" <<'EOF'
aidoctor-deploy ALL=(root) NOPASSWD: /usr/local/sbin/aidoctor-autodeploy *
EOF
chmod 440 "$sudoers"
visudo -cf "$sudoers"

# Обязательный отказ от прямого входа под этим пользователем по паролю.
# Пароли root и работающую SSH-сессию этот этап не меняет.
echo "ГОТОВО: учётная запись aidoctor-deploy и запрет произвольных SSH-команд."
echo "Проверить доступ ключом с Windows: ssh -i ~/.ssh/aidoctor_actions_deploy aidoctor-deploy@185.200.179.238 'deploy 0000000000000000000000000000000000000000'"
echo "Этот пробный SHA не должен обновить приложение, но проверит подключение."
echo "После добавления Secrets и переменной GitHub запустите первый push/Run workflow."
