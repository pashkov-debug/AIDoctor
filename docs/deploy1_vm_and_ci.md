# DEPLOY-1 — VPS, разделение окружений и диагностика CI

## Состояние на 24.10.2026

Изучен архив `AIDoctor-master (8).zip` (360 записей, 24 миграции, 86 модулей тестов).
Исходный `compose.yaml` поднимает **только PostgreSQL 16** и предназначен для
локальной разработки; не заменять его серверным Compose. В архиве присутствуют
`backend/app`, `backend/alembic`, `scripts/mock_ai_server.py`,
`scripts/smoke_ai_connection.py`, `backend/cdr_image/Dockerfile`,
`.github/workflows/ci.yml`. Секреты по именам файлов не найдены, однако
содержимое всей истории Git/репозитория не проверено.

Из снимка GitHub Actions 23.10.2026 видно, что прервался этап «Статические
проверки». Детальные логи не доступны без авторизации; ошибка конкретной
команды (Ruff check / Ruff format / Node / compileall) **не подтверждена**.
Node `--check` и `compileall` по архиву выполнены успешно на доступной машине.
Четыре новых DEPLOY-1 теста выполнены успешно (`4 passed`);
синтаксис shell и YAML разобран локально. Валидация Docker Compose
посредством самого Docker пока не выполнялась.
Ruff, Docker, PostgreSQL и Python 3.12 в окружении проверки недоступны.
В workflow команды разведены по шагам, закреплён Ubuntu 24.04 и обновлены
действия checkout/setup-python. Это улучшает диагностику и устраняет
предупреждение о Node 20, но НЕ гарантирует зелёный CI.

## Архитектура

Браузер → Caddy (localhost до аудита) → FastAPI → PostgreSQL 16
                                                ↘ том медицинских вложений

Caddy: автоматический TLS; для localhost — локальный CA, для своего домена —
обычный ACME после DNS и открытия портов 80/443.
PostgreSQL не публикует порты; FastAPI тоже. Сеть БД внутренняя.
Контейнер FastAPI работает без root; каталог вложений в постоянном томе.
Клинические контракты и миграции **не изменены**. LLM/MCP не разворачиваются.

**Единый источник истины:** PostgreSQL; пароль БД задаётся только переменной
`DB_PASSWORD` и используется Compose при создании PostgreSQL и DATABASE_URL.
Не переносить локальную БД `aidoctor` на сервер.

## Требования VPS

Ubuntu Server 24.04 LTS, x86-64, 4 vCPU, 8 ГБ RAM, 80 ГБ NVMe, внешний IPv4,
доступ SSH по ключу, домен под вашим управлением (не psihologpashkov.ru),
снимки/резервные копии у провайдера плюс независимые внешние копии.
Без GPU; ClamAV по умолчанию выключен — включать после отдельного теста памяти
и антивирусного контейнера.

**Оплата и география:** FirstVDS позволяет оплатить рублями и российскими
картами сервер в Амстердаме (см.
https://firstvds.ru/products/vps_vds_netherlands), а также указывает
в официальной справке поддержку отдельных иностранных карт.
Тариф «Отрыв» 4 vCPU/8 ГБ/80 ГБ NVMe — 1819 руб./мес. по прайсу
от 07.09.2026; итог для локации и дополнительных услуг проверить в корзине.
Альтернативы — Timeweb Cloud и Selectel.

**Важно:** Россия отсутствует в списке стран OpenAI API; Нидерланды
в список входят. Размещение сервера в поддерживаемой стране само по себе не
гарантирует доступ: страна клиента, регистрация и платёжные реквизиты также
должны соответствовать условиям сервиса.
https://help.openai.com/en/articles/5347006-openai-api-supported-countries-and-territories
При реальных пациентах выбрать страну и обработчика данных по требованиям
применимого права отдельно. Это не разрешение переносить медданные за рубеж.

На первоначальном этапе работают **только синтетические пациенты**,
никаких реальных клинических данных. Публичный доступ откладывается до
проверки auth, rate limiting, файлового AV/CDR и журналов безопасности.

## Первые команды на Linux (после аренды VPS)

Установить Docker Engine + Compose Plugin из официального репозитория Docker
для Ubuntu по актуальной инструкции:
https://docs.docker.com/engine/install/ubuntu/

Проверка:

```bash
docker --version
docker compose version
```

Разместить проект в выделенном каталоге без `.env` и локальных данных.
В корне проекта:

```bash
cp deploy/env.production.example .env.production
python3 -c 'import secrets; print(secrets.token_urlsafe(36))'
chmod 600 .env.production
```

Сначала вставьте случайный пароль в `DB_PASSWORD` (только URL-safe, без пробелов и
спецсимволов `%`, `@`, `/` и т.д.) и сохраните `AIDOCTOR_DOMAIN=localhost`,
`BIND_ADDRESS=127.0.0.1`.

Проверить итоговую конфигурацию **без вывода её в общедоступные логи**
(в `docker compose config` содержится пароль!):

```bash
docker compose --env-file .env.production -f deploy/compose.yaml config -q
docker compose --env-file .env.production -f deploy/compose.yaml build app
docker compose --env-file .env.production -f deploy/compose.yaml up -d postgres
docker compose --env-file .env.production -f deploy/compose.yaml run --rm app   python -m alembic -c alembic.ini upgrade head
docker compose --env-file .env.production -f deploy/compose.yaml up -d
docker compose --env-file .env.production -f deploy/compose.yaml ps
curl -kfsS https://localhost/api/v1/health
python3 deploy/smoke_deploy.py https://localhost --local-ca
```

`--local-ca` разрешён только для localhost: он не проверяет цепочку
сертификата. Публичный smoke-test запускается **без** этого флага.

Доступ к первоначальному HTTPS-сайту с рабочего ПК:

```powershell
ssh -L 8443:127.0.0.1:443 <linux-user>@<server-ip>
```

Затем локально в другом терминале:

```powershell
curl.exe -k https://localhost:8443/api/v1/health
```

Это только временная проверка через SSH, **не** публичная эксплуатация.
Не раскрывать пароли в командной строке. Пароль `DB_PASSWORD` не менять
на существующем томе простым изменением `.env.production`: PostgreSQL сохраняет
первоначального пользователя/пароль.

## Для перехода на публичный HTTPS (не выполнять до аудита)

1. Создать свой домен и DNS A-запись на IPv4 сервера.
2. Проверить правила firewall: SSH только с разрешённых IP; 80/443 для TLS;
   PostgreSQL 5432 и FastAPI 8000 публично недоступны.
3. Завершить проверку авторизации, ограничения попыток входа, CDR/AV загрузок,
   бизнес-логики согласования AI и изоляции пациентов.
4. Изменить только `AIDOCTOR_DOMAIN` на свой домен и `BIND_ADDRESS=0.0.0.0`,
   перезапустить proxy. Проверить валидный публичный сертификат без `-k`.
5. Предусмотреть отдельный механизм запрета доступа к API реальных пациентов,
   пока медицинский контур не прошёл аудит.

## Резервное копирование и восстановление

Запуск:

```bash
sh deploy/backup.sh
```

Скрипт делает `pg_dump -Fc`, архив вложений, SHA256 и сохраняет в
`$HOME/aidoctor-backups/<UTC timestamp>` с правами 0700. Не использует
`pg_dumpall`, не удаляет ничего. Копии содержат медицинские данные —
**шифруйте вне сервера**, ограничьте доступ и проверяйте ротацию.
Автоматический cron/таймер на этом этапе не включён.

Проверка восстановления **только в новой базе**, никогда в основной:

```bash
docker compose --env-file .env.production -f deploy/compose.yaml exec -T postgres   psql -U aidoctor -d postgres -v ON_ERROR_STOP=1   -c 'CREATE DATABASE aidoctor_restorecheck'
docker compose --env-file .env.production -f deploy/compose.yaml exec -T postgres   pg_restore --exit-on-error --no-owner --no-acl -U aidoctor   -d aidoctor_restorecheck < /путь/к/database.dump
docker compose --env-file .env.production -f deploy/compose.yaml exec -T postgres   psql -U aidoctor -d aidoctor_restorecheck -c '\dt'
```

Каталог вложений восстанавливать **только** в отдельный временный каталог,
не поверх работающего контейнера:

```bash
mkdir -p /tmp/aidoctor-restorecheck
tar -tzf /путь/к/attachments.tar.gz | head
tar -xzf /путь/к/attachments.tar.gz -C /tmp/aidoctor-restorecheck
```

Перед распаковкой архива из недоверенного источника требуется проверка путей,
символических ссылок и содержимого; не распаковывать недоверенные архивы как root.
Удаление временной тестовой базы — вручную только после проверки данных.

## Диагностика CI (Windows PowerShell из корня проекта)

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check backend
python -m ruff format --check backend
node --check backend/app/web/assets/app.js
python -m compileall -q backend/app
python -m pytest backend/tests/test_deploy1_configuration_unit.py -q
```

Если Ruff сообщает отклонения, показать его точный текст. Локально можно
выполнить разрешённую автоматическую правку:

```powershell
python -m ruff check backend --fix
python -m ruff format backend
python -m ruff check backend
python -m ruff format --check backend
```

В этой поставке автоправка Ruff **не выполнялась**: инструмент недоступен в
среде аудита. Нельзя считать CI исправленным до успешного нового запуска.

Тесты PostgreSQL — только по подтверждённой выделенной тестовой БД:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m pytest backend/tests -q -rs
Remove-Item Env:TEST_DATABASE_URL -ErrorAction SilentlyContinue
```

Проверить, что база `aidoctor_test` действительно существует и не содержит
необратимых данных перед запуском: тестовая фикстура удаляет таблицы.

## Проверка направления Site Builder

По актуальной документации ChatGPT Sites позволяет добавить MCP-инструменты
к Site и создать из них plugin после публикации. Это **не** означает,
что FastAPI может автоматически вызвать существующего агента ChatGPT
как синхронный LLM API и получить JSON-ответ обратно.

Для пилота: read-only MCP-инструмент с разрешёнными синтетическими данными;
отдельно подтвердить возможность обратного вызова. Не создавать клинические
записи через MCP, не пересылать реальные данные или токены пациентов.
См. https://help.openai.com/en/articles/20001547-hosting-a-plugin-with-chatgpt-sites

## Конфликты и ограничения

- **Владение:** PostgreSQL сохраняет факты; AI не пишет в клинические таблицы.
- **Контракты:** текущие API и Alembic без изменений, серверный Compose отдельно
  от локального `compose.yaml`; учесть внешние API при публичном доступе.
- **Эволюция:** отдельный reverse proxy и будущий Agent Gateway, без
  связывания FastAPI с конкретным Site Builder/LLM.
- **Секреты:** `.env.production` исключён существующим `.gitignore`, Docker
  build использует allowlist в `.dockerignore`; Compose config содержит пароль.
- **Наблюдаемость:** технические ошибки через `docker compose logs`, URL
  запросов с ID пациентов специально не логируются. Отдельный мониторинг,
  SIEM и бизнес-аудит ещё не настроены.
- **Граница безопасности:** эта конфигурация — закрытый серверный пилот,
  а не медицинский production; нет подтверждённых нагрузочных и security тестов.

## Критерии готовности DEPLOY-1

1. `docker compose config -q` выполняется без ошибок.
2. Сервисы postgres, app, proxy healthy/running.
3. `alembic upgrade head` применяется на новой БД без ошибок.
4. HTTPS smoke-test возвращает `/api/v1/health` и `/app`.
5. Порты 5432 и 8000 не опубликованы в сети VPS.
6. `backup.sh` и восстановление в `aidoctor_restorecheck` проверены на VPS.
7. GitHub Actions проходит целиком, включая Ruff и PostgreSQL pytest.

**Фактическая приёмка** пунктов 1–7 возможна только после запуска на
Linux с Docker, рабочими DNS и GitHub. Наличие файлов не равно проверке
production-эксплуатации.
