# AIDoctor — автоматическая выкладка на FirstVDS (только синтетическая БД)

**Сервер:** `185.200.179.238`, Ubuntu 24.04, Docker/Compose уже установлены.  
**GitHub:** `https://github.com/pashkov-debug/AIDoctor`, основная ветка `master`.  
**Условие:** работает закрытый тестовый AIDoctor из архива в
`/opt/aidoctor/AIDoctor`, присутствует `.env.test`, текущие Docker-тома не удалены.

## Что происходит после настройки

`push master` → GitHub Actions (Ruff / JS / Python) → SSH-ключ отдельного пользователя
`aidoctor-deploy` → root-owned служебный скрипт → `git fetch` конкретного SHA
→ `pg_dump` тестовой БД → Docker build → Alembic `upgrade head` →
пересоздание **только app** → HTTP/SQL smoke-test.

- База `aidoctor_synthetic`, том `aidoctor-vds-test_pg_synthetic`, вложения и
  `.env.test` сохраняются; PostgreSQL не пересоздаётся; seed **не запускается**.
- Старый развернутый код из ZIP остаётся в `/opt/aidoctor/AIDoctor` как нетронутая папка.
  Автодеплой использует `/opt/aidoctor/git-checkout` и те же именованные Docker-тома.
- Нет `docker compose down -v` и нет `docker system prune`.
- Доступ к приложению остаётся **только** через SSH-туннель
  `http://127.0.0.1:18080/app`. HTTPS-публикации пока нет.
- Автодеплой по `push` включается только после установки SSH и GitHub Secrets.
- Модульные/PG тесты в GitHub остаются ручными; автоматический Ruff обязателен.

## Шаг 1 — разместить единственный ZIP в Git-репозитории на Windows

Открой **PowerShell на Windows**:

```powershell
$folder = "C:\Users\pashk\OneDrive\Desktop\Новая папка\Новая папка"
cd "$folder"
git rev-parse --show-toplevel
```

Если получена ошибка `not a git repository`, сначала сделай отдельную копию
*именно Git-репозитория* в новой папке:

```powershell
git clone https://github.com/pashkov-debug/AIDoctor.git "$folder\AIDoctor-git"
cd "$folder\AIDoctor-git"
```

Если `git rev-parse` уже показал корень AIDoctor, оставайся в нём.
Далее в обоих случаях:

```powershell
$repo = (git rev-parse --show-toplevel).Trim()
Expand-Archive -LiteralPath "$folder\AIDoctor_AUTODEPLOY_MASTER_2026-10-24.zip" -DestinationPath "$repo" -Force
cd "$repo"
git status --short
```

Пакет содержит **полные файлы**, поэтому не переносить их вручную фрагментами.

Выполни локальную проверку (без удаления медицинских данных):

```powershell
python -m ruff check backend
python -m ruff format --check backend
node --check backend/app/web/assets/app.js
python -m pytest backend/tests/test_ci_autodeploy_unit.py -q
python -m pytest backend/tests/test_vds_synthetic_unit.py -q
```

Если всё прошло, отправь изменение в `master`:

```powershell
git add .github/workflows/ci.yml .dockerignore README.md deploy docs backend/scripts/seed_vds_synthetic.py backend/tests/test_ci_autodeploy_unit.py backend/tests/test_vds_synthetic_unit.py
git commit -m "ci: configure automatic synthetic VDS deployment"
git push origin master
```

**Первый push не развернёт приложение**, пока не включена репозиторная
переменная `VDS_AUTODEPLOY_ENABLED=true`. Это специально, чтобы не
запускать деплой до установки ключей.

## Шаг 2 — один раз создать ключ для GitHub Actions на Windows

В PowerShell:

```powershell
$key = "$env:USERPROFILE\.ssh\aidoctor_actions_deploy"
if (-not (Test-Path $key)) {
    ssh-keygen -t ed25519 -f $key -C "AIDoctor GitHub Actions"
}
```

На вопрос о passphrase **дважды нажми Enter** для пустой passphrase:
GitHub Actions не сможет вводить пароль интерактивно.
Ключ предназначен только для этого автоматического деплоя.

Проверь, что отпечаток сервера ранее был сверён через доверенную
консоль VMmanager. Используй уже принятый Windows SSH host-key, не
скачивай его заново без сверки:

```powershell
ssh-keygen -F 185.200.179.238 -f "$env:USERPROFILE\.ssh\known_hosts"
```

Если команда не показывает ключ — **не продолжай до проверки host-key**.

Передай на VDS только публичный ключ и четыре установочных файла:

```powershell
scp "$key.pub" root@185.200.179.238:/root/aidoctor_actions_deploy.pub
scp "$repo\deploy\ci\bootstrap_autodeploy.sh" root@185.200.179.238:/root/bootstrap_autodeploy.sh
scp "$repo\deploy\ci\server_autodeploy.sh" root@185.200.179.238:/root/server_autodeploy.sh
scp "$repo\deploy\ci\ssh_deploy_dispatch.sh" root@185.200.179.238:/root/ssh_deploy_dispatch.sh
scp "$repo\deploy\ci\verify_compose.py" root@185.200.179.238:/root/verify_compose.py
```

Это последняя загрузка файлов вручную для настройки доставки.
**Приватный ключ НЕ копируется на VDS и НЕ коммитится в Git.**

## Шаг 3 — настроить сервер на Ubuntu

Открой SSH:

```powershell
ssh root@185.200.179.238
```

В терминале `root@pashkovnpc:~#`:

```bash
bash /root/bootstrap_autodeploy.sh
```

Скрипт создаёт `aidoctor-deploy`, запрещает парольный вход этой
учётной записи, ограничивает ключ одной командой `deploy <SHA>`,
устанавливает root-owned deploy runner и отдельный Git checkout.
**Старую папку, пароли и Docker-тома не удаляет.**

При необходимости проверь доступ к ограниченному SSH-ключу с Windows
(в новом окне PowerShell):

```powershell
ssh -o IdentitiesOnly=yes -i "$env:USERPROFILE\.ssh\aidoctor_actions_deploy" aidoctor-deploy@185.200.179.238 "deploy 0000000000000000000000000000000000000000"
```

Ожидаемо ответит, что коммит устарел, и завершится без изменения приложения.
Это проверка ключа, не реальный деплой.

## Шаг 4 — GitHub Secrets и переменная включения

Открой [GitHub → AIDoctor → Settings → Secrets and variables → Actions]
(https://github.com/pashkov-debug/AIDoctor/settings/secrets/actions).

В разделе **Repository secrets** добавь:

1. `VDS_SSH_PRIVATE_KEY` — содержимое приватного файла
   `$env:USERPROFILE\.ssh\aidoctor_actions_deploy` (включая BEGIN/END).
2. `VDS_SSH_KNOWN_HOSTS` — результат `ssh-keygen -F` для IP сервера из уже
   проверенного `$env:USERPROFILE\.ssh\known_hosts`.

Чтобы безопасно скопировать значения в буфер обмена:

```powershell
Get-Content -Raw "$env:USERPROFILE\.ssh\aidoctor_actions_deploy" | Set-Clipboard
# Вставить в VDS_SSH_PRIVATE_KEY, затем очистить буфер после добавления.
ssh-keygen -F 185.200.179.238 -f "$env:USERPROFILE\.ssh\known_hosts" | Set-Clipboard
# Вставить в VDS_SSH_KNOWN_HOSTS
Set-Clipboard -Value ""
```

Затем **Repository variables → New repository variable**:

- имя: `VDS_AUTODEPLOY_ENABLED`
- значение: `true`

Секреты нельзя публиковать в Issue, README, Actions logs или присылать в чат.

## Шаг 5 — первый автодеплой и каждый последующий push

После включения переменной нужно сделать следующий `push` в `master`
(начальный push из шага 1 произошёл ещё до включения).

Для первого запуска достаточно пустого коммита:

```powershell
cd "$repo"
git commit --allow-empty -m "ci: activate automatic VDS deployment"
git push origin master
```

Открой <https://github.com/pashkov-debug/AIDoctor/actions> →
«Проверка AIDoctor» → новый запуск → `Автоматическое обновление закрытого VDS`.

Далее при **каждом** push в `master` GitHub автоматически обновляет
сервер после успешной статической проверки. PR **никогда** не деплоит.

Открыть сайт с Windows (в отдельном терминале):

```powershell
ssh -N -L 18080:127.0.0.1:18080 root@185.200.179.238
```

Сайт: <http://127.0.0.1:18080/app>.

Проверить на VDS:

```bash
cat /opt/aidoctor/last_deployed_sha
cd /opt/aidoctor/git-checkout
git rev-parse HEAD
docker compose --env-file .env.test -f deploy/compose.test.yaml ps
bash deploy/02_check_test.sh
ls -lh /opt/aidoctor/backups/
```

Для ручной остановки автоматических выкладок **не нужно выключать сервер**:
поменяй GitHub Variable `VDS_AUTODEPLOY_ENABLED` на `false`.
При изменении инфраструктурных служебных файлов под `/usr/local/sbin`
нужно повторно выполнить bootstrap — они намеренно не обновляются из Git.

## Откат / восстановление / ограничения

- Если build или smoke-test завершились ошибкой, скрипт пытается вернуть
  предыдущий Docker-образ и прежний Git SHA.
- Alembic миграции уже могли примениться — автоматического downgrade нет.
  Перед каждым обновлением создаётся резервная копия
  `/opt/aidoctor/backups/aidoctor_synthetic_...dump` с правами 0600.
- Копии **не проверялись восстановлением** и могут содержать секретные
  (хотя синтетические) данные. План восстановления проверяется отдельно.
- Не удаляй `aidoctor-vds-test_pg_synthetic` и
  `aidoctor-vds-test_attachments_test`; НЕ используй `down -v`.
- Любой пользователь с правом push в `master` фактически получает
  возможность менять исполняемый код сервера; защищай GitHub-аккаунт 2FA,
  ветку и SSH-ключ деплоя.
- Не направляй разрушительные pytest-тесты на `aidoctor_synthetic`.
  Отдельная `aidoctor_test` существует специально для них.
- Это закрытый **синтетический** контур, а не production.
  Пять предыдущих падений pytest не исправлены и клиническая готовность
  не подтверждена.
- Если GitHub станет недоступен с VDS, `git fetch` завершится ошибкой,
  контейнеры останутся в прежнем состоянии.
- Публичный HTTPS, Site Builder и AI-модель здесь не подключаются.

## Три конфликта и инварианты

**Владение данными:** существующий PostgreSQL volume — источник истины;
автодеплой не выполняет seed и не удаляет записи или вложения.

**Контракты:** команда деплоя использует точный Git SHA и прежние
`deploy/compose.test.yaml`, `APP_ENV=test`, порт localhost и миграции Alembic;
проверка Compose запрещает подмену томов или открытие портов.

**Эволюция:** новые сервисы/публичные порты потребуют отдельного одобрения
и изменений в защитном валидаторе, а не тихой автоматической публикации.

## Критерии готовности

1. Первый push в `master` проходит Ruff, JS, Python.
2. Job `Автоматическое обновление закрытого VDS` становится зелёным.
3. `last_deployed_sha` равен Git commit на сервере.
4. Доступно `/app` по SSH-туннелю и `environment=test` в health endpoint.
5. Есть новая непустая `pg_dump` перед обновлением.
6. Три синтетических пациента остались, учебные черновики — `draft`.
7. PostgreSQL не опубликован, FastAPI остался на `127.0.0.1:18080`.
