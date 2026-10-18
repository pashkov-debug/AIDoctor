# AIDoctor — универсальная медицинская платформа

**Статус:** активная разработка. **Не использовать с реальными данными пациентов до отдельного аудита безопасности, эксплуатации и законодательства.**

- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16+, Docker.
- Рабочая среда: Windows 11, PyCharm, PowerShell.
- Единственная серверная SQL-БД: **PostgreSQL + psycopg 3**. SQLite исключён.
- Версионированный HTTP API: `/api/v1`.
- Пользователи: врач, пациент, администратор с разными правами.

## Цель проекта

AIDoctor — не узкоспециализированное приложение только для тревоги и депрессии,
а универсальная платформа для наблюдений, истории обследований, назначения
дальнейших диагностических шагов и коммуникации пациента с врачом.

Внешний LLM в целевой архитектуре будет формировать предложения медицинского
анализа, обследований, маршрутизации, препаратов и дозировок. Эти результаты
**не должны исполняться автоматически**: врач подтверждает, исправляет или
возвращает их на доработку с комментарием. До интеграции модели это
проектные требования, а не работающий функционал.

## Что уже реализовано

- FastAPI-маршруты пациентов, визитов, опросников и событий истории.
- Учётные записи и bearer-сессии; серверная проверка ролей и доступа к пациенту.
- Связи `DoctorPatient`, soft-delete пациентов и PostgreSQL-only конфигурация.
- Таблицы наблюдений и вложений; локальный API загрузки, списка и скачивания
  PDF, DOC/DOCX, изображений и аудио с проверкой прав.
- Файлы загружаются со статусом `quarantined`. Сканер вредоносных файлов,
  распознавание, расшифровка аудио и извлечение медицинских данных **не готовы**.
- **Context Builder v1**: структурированные факты с идентификаторами источников,
  исключением заменённых записей, SHA-256 и указанием усечения.
- **Digest v2**: количественная сводка без медицинских интерпретаций.
- **Delta v2**: сравнение клиентского baseline с текущим контекстом;
  клиентский SHA-256 сам по себе **не доказывает происхождение baseline**.
- **Context Snapshots v3 (проверено локально)**: серверные версии клинического
  контекста, хранимые в PostgreSQL JSONB, сравнение по серверному `snapshot_id`.
  Миграция `aictx_v3_20261017` применена, пользователь подтвердил зелёный pytest
  и `alembic check` без новых операций.

### API контекста

| Метод и маршрут относительно `/api/v1` | Назначение |
|---|---|
| `GET /patients/{patient_id}/context` | Текущий структурированный контекст |
| `GET /patients/{patient_id}/context/digest` | Состав и даты фактов |
| `POST /patients/{patient_id}/context/delta` | Сравнение с присланным клиентом baseline (v2) |
| `POST /patients/{patient_id}/context/snapshots` | Создать серверный снимок, ответ `201` |
| `GET /patients/{patient_id}/context/snapshots` | Список последних 50 снимков |
| `GET /patients/{patient_id}/context/snapshots/{snapshot_id}` | Прочитать сохранённую версию |
| `POST /patients/{patient_id}/context/snapshots/{snapshot_id}/delta` | Сравнить снимок с текущим контекстом |

Весь API контекста доступен авторизованному врачу/администратору
**при наличии права на пациента**. Анонимным пользователям — `401`,
чужим врачам — `404`. API пациента не должен передавать медконтекст в LLM
без дополнительной проверки прав и согласия.

Снимки содержат **полный допустимый JSON контекста**, а не только хэш.
Сохраняются только неусечённые снимки, до 400 фактов и 512 КиБ.
Содержимое файлов во временном карантине в контекст не включается.
Снимки через API не редактируются. Для production необходимы
шифрование, аудит доступа, политика retention и резервное копирование.

**Safety 5.8:** новые тесты и команды представлены в
[docs/safety_read_audit_v1.md](docs/safety_read_audit_v1.md).
Для локального проекта нужно подтвердить миграцию, Ruff и полный pytest.

**Исправление 5.8 (Ruff B007):** в PostgreSQL-тесте аудита чтений
удалена неиспользуемая переменная цикла. Логика проверок и миграции
не меняются. После применения локальных автоматических исправлений Ruff
нужно повторно выполнить `ruff check` и полный `pytest`.

### Этап 5.1 — ручные сигналы (локальные тесты пройдены)

Реализован отдельный контур **ручных** сигналов для врача, без вызова LLM
и без автоматического клинического триажа. Операции относительно `/api/v1`:

| Метод и маршрут | Назначение |
|---|---|
| `POST /patients/{patient_id}/safety-alerts` | Создать сигнал (`201`) |
| `GET /patients/{patient_id}/safety-alerts` | Последние 100 сигналов |
| `POST /patients/{patient_id}/safety-alerts/{alert_id}/ack` | Идемпотентно подтвердить просмотр |

Запись создаёт врач или администратор с правом на пациента.
Подтверждение записывается в PostgreSQL вместе с событием журнала;
повторное подтверждение не порождает дубль события. `404` скрывает
чужих пациентов; пациентский доступ к внутренним сигналам пока закрыт.
`delivery_status: not_configured` — историческое поле API; с 5.6 оно **не отражает** фактическую запись в `in_app` inbox.
Это **не сервис экстренной помощи** и не система клинической оценки рисков.

Документация: [docs/safety_alerts_v1.md](docs/safety_alerts_v1.md).

### Этап 5.2 — PostgreSQL Outbox (локальная проверка подтверждена пользователем)

Атомарно с созданием ручного Safety Alert записываются `safety_outbox` и
`enqueued` в `safety_outbox_events`. Есть резервирование записей через
`FOR UPDATE SKIP LOCKED`, lease, три попытки с backoff, восстановление
просроченных резервирований, технический аудит переходов и защита от
устаревших токенов. **Worker и внешняя отправка не запущены**.
`delivery_status = "not_configured"` остаётся неизменным.
Миграция `aisafe_v2_20261018` применена по сообщению пользователя;
её точный вывод Alembic в переписке не приводился.

Документация: [docs/safety_outbox_v1.md](docs/safety_outbox_v1.md).

### Этап 5.3 — Idempotency-Key для ручного POST

Для `POST /patients/{patient_id}/safety-alerts` можно передать заголовок
`Idempotency-Key` (8–128 символов ASCII, рекомендуемый UUIDv4).
Повтор того же ключа для того же врача и пациента с тем же семантическим
телом возвращает **тот же `alert_id`**, не создавая второй сигнал, Outbox
или аудит создания. При изменённом теле возвращается `409`, при неверном
ключе — `400`. Без заголовка POST по-прежнему создаёт новый сигнал.
Проверки доступа сохраняются. Для повторов возвращается **текущее
состояние** существующего сигнала с кодом `201`, а не сохранённый JSON
первого ответа.

Ключи и отпечатки запросов хранятся в новой PostgreSQL-таблице
`safety_alert_requests` как SHA-256; исходные значения ключей не сохраняются.
Все связанные записи создаются атомарно; конкурентные запросы
дедуплицируются на UNIQUE в PostgreSQL. Миграция
`aisafe_v3_20261018` поверх `aisafe_v2_20261018`.

Пользователь сообщил о 134 зелёных тестах после этапа 5.4.
Внешней доставки уведомлений нет.

Документация: [docs/safety_idempotency_v1.md](docs/safety_idempotency_v1.md).


### Этап 5.4 — изолированный исполнитель Outbox

Добавлен `app.workers.safety_outbox`: библиотечный вызов `process_one` для
**одной** записи Outbox, с отдельными SQLAlchemy Session для резервирования и
завершения и транспортным интерфейсом `DeliveryTransport`. Присутствует
защитный отказ без транспорта, нормализация кодов ошибок, проверка
подтверждения, защита от устаревшего lease и тестовый синтетический транспорт.

**Нет реального транспорта, получателей, автоотправки, запущенного
процесса worker или расписания**. API не изменён; `delivery_status =
"not_configured"` остаётся прежним. Нет новых миграций: для 5.4
ожидаемый Alembic head = `aisafe_v3_20261018`.

Безопасная CLI-диагностика (агрегаты, read-only, без claim):

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
python -m app.workers.safety_outbox --status
Remove-Item Env:PYTHONPATH
```

Документация: [docs/safety_worker_v1.md](docs/safety_worker_v1.md).



### Этап 5.5 — настройки внутренних уведомлений

Добавлены серверные маршруты `in_app` для **собственного аккаунта врача**:
отдельная таблица `safety_notification_routes`, аудит изменений,
проверка связи `DoctorPatient`, soft-delete и роли. Врач включает
или отключает маршрут через авторизованный API:

| Метод и путь относительно `/api/v1` | Назначение |
|---|---|
| `GET /patients/{patient_id}/safety-notification-route` | Прочитать собственную настройку (`null`, если отсутствует) |
| `PUT /patients/{patient_id}/safety-notification-route` | Установить `{"enabled":true/false,"channel":"in_app"}` |

Повторное PUT с тем же состоянием не добавляет событие в аудит.
Подтверждение относится только к **внутренней учётной записи** врача;
email/SMS/внешние контакты и согласие пациента пока не подтверждаются.

**Включение маршрута НЕ запускает отправку.** С этапа 5.6 эти настройки
использует только локальный in_app-адаптер при отдельном запуске.
Внешней доставки нет. `delivery_status` в Safety Alerts остаётся
`not_configured`. Миграция:
`aisafe_v4_20261018`, предшественник `aisafe_v3_20261018`.

Подробности: [docs/safety_notification_routes_v1.md](docs/safety_notification_routes_v1.md).

### Этап 5.6 — локальный in_app inbox и ручной исполнитель

Реализовано: одна техническая запись `safety_in_app_notifications`
на событие Outbox и получателя. `UNIQUE(outbox_id, recipient_user_id)`
защищает от повторной записи после потери подтверждения между двумя
транзакциями. Адаптер разрешает доставку только при действующем
opt-in `in_app`, активной связи `DoctorPatient` и неудалённом пациенте.
Для решения о доставке маршрут и связанные данные блокируются до commit.

Добавлен `GET /api/v1/safety-inbox` — последние 50 внутренних уведомлений
**только текущего врача**, с повторной проверкой связи и soft-delete
при чтении. Содержимое: только ID уведомления, пациента, сигнала и время
записи; медицинских текстов, адресов, телефонов нет.
Подтверждение означает запись в БД, **не прочтение врачом**.

**По умолчанию выключено.** Для запуска требуются
`SAFETY_IN_APP_DELIVERY_ENABLED=true` и отдельный CLI `--once`.
Каждый запуск обрабатывает **не больше одного** сообщения Outbox.
Автоматического worker-цикла, реального SMTP/SMS/push, scheduler и
внешней доставки нет. Исторический API `delivery_status: not_configured`
не меняется и не отражает статус нового inbox.

Миграция: `aisafe_v5_20261018` после `aisafe_v4_20261018`.
Интеграционные PostgreSQL-тесты и Ruff нужно подтвердить в Windows.

Документация: [docs/safety_in_app_v1.md](docs/safety_in_app_v1.md).

### Этап 5.7 — административные follow-up, защита от частых уведомлений

Добавлен отдельный **контрольный список непросмотренных ручных сигналов**
без отправки новых уведомлений и без клинической классификации. Сигнал
с `status="open"` попадает в список не ранее чем через **24 часа**, только
при включённом `in_app`-маршруте врача и действующей связи `DoctorPatient`.

Новая таблица `safety_followups` хранит только технические ID и время.
Одна запись на пару «сигнал — врач» за всё время; ограничение **5 записей
на врача за последние 24 часа**, атомарные блокировки PostgreSQL и UNIQUE.
Повторные запуски не создают дублей. Если лимит исчерпан, запись
откладывается до следующего отдельного запуска после освобождения окна.
Подтверждение сигнала скрывает follow-up из списка, сохраняя историю.

`GET /api/v1/safety-followups` — до 50 открытых контрольных отметок
текущего врача. Доступ пациентам и администратору запрещён. Проверки
действующей связи/удаления пациента/отключения маршрута повторяются при
каждом чтении.

**Нет автоматического расписания, SMS/email/push, повторного вызова
Outbox и гарантии врачебного ответа.** Технический интервал в 24 часа
не является клиническим SLA. Создание отметки требует однократного CLI
при `SAFETY_FOLLOWUP_SCAN_ENABLED=true`. По умолчанию `false`.
Миграция `aisafe_v6_20261018` поверх `aisafe_v5_20261018`.

Ручная проверка (при явно включённом маршруте врача):

```powershell
$env:PYTHONPATH = (Resolve-Path .\\backend).Path
$env:SAFETY_FOLLOWUP_SCAN_ENABLED = "true"
python -m app.workers.safety_followup_once --once
Remove-Item Env:SAFETY_FOLLOWUP_SCAN_ENABLED
Remove-Item Env:PYTHONPATH
```

До миграции: `current = aisafe_v5_20261018`, `heads = aisafe_v6_20261018`.
После `upgrade head` оба должны указывать на `aisafe_v6_20261018`.

```powershell
docker compose up -d postgres
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini heads
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini check

python -m ruff check backend
python -m pytest backend/tests/test_safety_followups_unit.py -v
$env:TEST_DATABASE_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m pytest backend/tests/test_safety_followups_pg.py -v -rs
python -m pytest backend/tests -v -rs
```

Документация: [docs/safety_followups_v1.md](docs/safety_followups_v1.md).


### Этап 5.8 — аудит успешных чтений и политика хранения

Новая таблица `safety_read_audit` (миграция `aisafe_v7_20261018` после
`aisafe_v6_20261018`) записывает каждый авторизованный GET для:
списка Safety Alerts, собственной настройки маршрута, `safety-inbox`
и `safety-followups`. Пишутся только ID пользователя/пациента (где
применимо), тип чтения, число элементов и время. **Без медицинского текста,
токенов, контактов и тела ответа.** Пустой успешный ответ тоже журналируется.

Запись коммитится до HTTP-ответа (fail-closed). Несанкционированные
попытки (`401/403/404`) в этот журнал не входят; для них нужен
специальный security-log. Областью действия 5.8 являются только
указанные четыре GET, а не весь API или файлы.

Удаление/TTL аудита **не включены**: сроки хранения зависят от
юрисдикции и юридического основания. Нет публичного API изменения журнала.
Downgrade миграции запрещён. Production-аудит безопасности,
шифрование, мониторинг, ограниченные SQL-роли, экспорт и восстановление
остаются отдельными обязательными задачами.

**Технический контур этапа 5 считается завершённым по сообщению
пользователя о зелёных проверках 5.8 в локальной среде.** Это не разрешение работать с реальными
медицинскими данными и не гарантия срочных уведомлений.

Документация: [docs/safety_read_audit_v1.md](docs/safety_read_audit_v1.md).

**Историческая проверка этапа 5.6 (не применять после 5.8 как upgrade-план):**

```powershell
docker compose up -d postgres
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini heads
# Ожидается ДО upgrade: current = aisafe_v4_20261018, heads = aisafe_v5_20261018
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini check

python -m ruff check backend
python -m pytest backend/tests/test_safety_in_app_unit.py -v

$env:TEST_DATABASE_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m pytest backend/tests/test_safety_in_app_pg.py -v -rs
python -m pytest backend/tests -v -rs
```

Тестовая фикстура удаляет и пересоздаёт таблицы только в локальной
PostgreSQL БД с суффиксом `_test`. Проверить, что integration-тесты не
отмечены `SKIPPED`, прежде чем считать инкремент готовым.

**Разовый запуск после отдельного включения врачом маршрута и проверки
миграции:**

```powershell
$env:PYTHONPATH = (Resolve-Path .\\backend).Path
$env:SAFETY_IN_APP_DELIVERY_ENABLED = "true"
python -m app.workers.safety_in_app_once --once
Remove-Item Env:SAFETY_IN_APP_DELIVERY_ENABLED
Remove-Item Env:PYTHONPATH
```

При отсутствии маршрута Outbox не считается доставленным: фиксируется
`route_unavailable` и назначается повтор по правилам 5.2.
После исчерпания трёх попыток нужен отдельный ручной разбор.
Для безопасной диагностики по-прежнему доступен `--status` из 5.4.

Подробности: [docs/context_snapshots_v3.md](docs/context_snapshots_v3.md).
Для загрузки файлов: [docs/attachments.md](docs/attachments.md).


### Этап 6.1 — непроверенные ручные выдержки из вложений

До запуска автоматического извлечения добавлена **ручная фиксация
происхождения выдержек**: врач указывает локатор (например, страницу)
и короткий текст, PostgreSQL хранит ссылку на вложение, SHA-256
вложения из метаданных и SHA-256 самой выдержки. Повторы одной записи
идемпотентны; успешные GET журналируются без содержимого.

| Метод относительно `/api/v1` | Действие |
|---|---|
| `POST /patients/{patient_id}/attachments/{attachment_id}/evidence-drafts` | Создать непроверенную выдержку (`201`) |
| `GET /patients/{patient_id}/attachments/{attachment_id}/evidence-drafts` | Прочитать до 50 выдержек (с аудитом) |

Входящие данные **только вручную от врача** с действующей связью с
пациентом; пациентам, администраторам и чужим врачам доступ запрещён.
`verification_status=unverified`, `source_kind=manual` — неизменяемые
серверные поля. Все вложения остаются `quarantined`, исходные байты
не читаются и автоматический OCR/LLM не запускается. Данные черновиков
**не попадают** в Context Builder и не становятся медицинскими фактами.
Нельзя интерпретировать эти строки как подтверждённые медицинские данные.

Новая миграция: `aiextract_v1_20261018` поверх `aisafe_v7_20261018`.
Новых зависимостей нет. Продуктовая безопасность и правила хранения
потенциально медицинского текста пока не завершены.
Подробности: [docs/attachment_evidence_v1.md](docs/attachment_evidence_v1.md).

Для установки в Windows (после подтверждения миграции 5.8):

```powershell
docker compose up -d postgres
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini heads
# Ожидается current: aisafe_v7_20261018 / heads: aiextract_v1_20261018
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini check
python -m ruff check backend
python -m pytest backend/tests/test_attachment_evidence_unit.py -v
$env:TEST_DATABASE_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m pytest backend/tests/test_attachment_evidence_pg.py -v -rs
python -m pytest backend/tests -v -rs
```

## Установка на Windows 11 / PyCharm

Из корня репозитория, в PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt

# Только если .env ещё отсутствует:
# Copy-Item .env.example .env

docker compose up -d postgres
python -m alembic -c alembic.ini upgrade head
```

Для снимков v3 (историческая команда; при уже применённой миграции повтор не нужен):

```powershell
python scripts/create_context_snapshots_migration.py
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current
python -m alembic -c alembic.ini check
```

Генератор создаёт ровно **одну** миграцию поверх текущего Alembic `head`,
отказывается работать при нескольких головах, не переписывает старые
миграции и безопасен при повторном запуске. Созданный файл в
`backend/alembic/versions/` следует добавить в Git.

### Текущая локальная установка

Для этапов 5.8 и 6.1 новых библиотек не требуется. Перед применением новой
миграции ожидается `current = aisafe_v6_20261018`, после `upgrade head` —
`aisafe_v7_20261018`. GET API с обязательным аудитом нельзя запускать до обновления БД.
Для нового клона репозитория сначала убедитесь, что весь исходный код,
модели, миграции и `main.py` внесены в Git; локальные архивы из истории
разработки не являются воспроизводимым способом развёртывания.

```powershell
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current
python -m alembic -c alembic.ini check
python -m ruff check backend
python -m pytest backend/tests -v -rs
```

Для обычных изменений используем полные файлы для прямой замены;
автоматические установщики и создание резервных копий не нужны.
Откат изменений выполняется средствами локального Git.

Запуск API:

```powershell
python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Swagger: http://127.0.0.1:8000/docs

## Тесты

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m ruff check backend
python -m pytest backend/tests/test_context_snapshots_unit.py -v
python -m pytest backend/tests/test_context_snapshots_api.py -v -rs
python -m pytest backend/tests/test_safety_alert_schema.py -v -rs
python -m pytest backend/tests/test_safety_alerts_api.py -v -rs
python -m pytest backend/tests/test_safety_router_registered.py -v -rs
python -m pytest backend/tests/test_safety_outbox_unit.py -v
python -m pytest backend/tests/test_safety_outbox_pg.py -v -rs
python -m pytest backend/tests/test_safety_idempotency_unit.py -v
python -m pytest backend/tests/test_safety_idempotency_pg.py -v -rs
python -m pytest backend/tests/test_safety_worker_unit.py -v
python -m pytest backend/tests/test_safety_worker_pg.py -v -rs
python -m pytest backend/tests/test_safety_notification_routes_unit.py -v
python -m pytest backend/tests/test_safety_notification_routes_pg.py -v -rs
python -m pytest backend/tests/test_safety_in_app_unit.py -v
python -m pytest backend/tests/test_safety_in_app_pg.py -v -rs
python -m pytest backend/tests/test_safety_followups_unit.py -v
python -m pytest backend/tests/test_safety_followups_pg.py -v -rs
python -m pytest backend/tests/test_safety_read_audit_unit.py -v
python -m pytest backend/tests/test_safety_read_audit_pg.py -v -rs
python -m pytest backend/tests -v -rs
python -m alembic -c alembic.ini current
python -m alembic -c alembic.ini check
```

Интеграционные тесты работают только с отдельной локальной PostgreSQL-БД
через `TEST_DATABASE_URL` с суффиксом `_test`. Фикстура создаёт и удаляет
**схему тестовой БД** — не направлять её на реальные данные.
Статус `SKIPPED` не засчитывается как успешная проверка интеграции.

**Исторический статус этапов 5.2–5.4 (18.10.2026):** после исправления
запуска Docker все тесты, Ruff и миграции 5.2 проходят. Конкретные логи
`alembic current`, количества тестов и предупреждений в переписке не
представлены. Пользователь впоследствии подтвердил 134 зелёных теста на этапе 5.4
и успешную работу этапов 5.5–5.7 без детальных логов в переписке.
После исправления Ruff B007 пользователь сообщил, что проверки 5.8
в порядке; точное количество тестов на этом шаге в переписке не приведено.
`SKIPPED` не засчитывается как пройденный PostgreSQL-тест.

## Владение данными и потоки

`врач / пациент → авторизованный API → PostgreSQL / файловое хранилище → Context Builder → (будущий) внешний LLM → предложение → решение врача`

- PostgreSQL — источник истины для пациентов, истории, метаданных, связей и
  серверных снимков контекста.
- Оригиналы вложений лежат в частном файловом хранилище, не в SQL и не в public/static.
- LLM **не получает доступ к БД**, не меняет историю и не утверждает лечение.
- Backend хранит решения и комментарии врача; сам медицинские выводы не создаёт.
- Алгоритмы Context/Digest/Delta детерминированны и не являются диагнозами.

## План 0–9

| Этап | Состояние |
|---|---|
| 0. Окружение | Локальное окружение и PostgreSQL настроены; CI ещё требуется |
| 1. Авторизация и права | Базовые маршруты защищены; production-аудит не завершён |
| 2. PostgreSQL, миграции, история, вложения | Базовый MVP проверен локально; промышленная безопасность хранилища отсутствует |
| 3. UI врача и пациента | Полноценные кабинеты впереди |
| **4. Context / Digest / Delta / Snapshots** | **Базовые функции и миграция v3 проверены локально; production-проверки впереди** |
| **5. Safety Alerts / Outbox / Audit** | **Технический контур 5.1–5.8 завершён по сообщению пользователя; production privacy/security и клинические гарантии не завершены** |
| 6. Извлечение файлов и внешний LLM | **6.1 — подтверждённые пользователем зелёные проверки; 6.2 — предпроверка и карантин (требует проверки в Windows); AV/парсера/LLM нет** |
| 7. Утверждение / изменение / доработка рекомендаций врачом | Не завершён |
| 8. Клинические тесты и демо чемпионата | Не завершён |
| 9. Интернет-релиз, аудит и испытания | Не завершён |

## Следующее направление после 6.2

**Рекомендовано:** после подтверждения 6.2 спроектировать 6.3 — реальный AV/CDR gate
и изолированную обработку документов, только с отдельного согласия. До проверки файлов автоматический
парсинг, OCR/STT, LLM и добавление черновиков в клинический контекст запрещены.
Внешний LLM — только после отдельного разрешения, модели угроз,
прав доступа и согласия на передачу данных. Полноценный UI (этап 3)
остаётся самостоятельной работой.

## Инварианты

1. PostgreSQL — единственная БД; не подключать альтернативную.
2. Не менять существующие маршруты `/api/v1` без тестов и версии контракта.
3. Факты и решения врача сохраняются с происхождением и временем.
4. Контекст не должен включать файлы, не прошедшие проверку безопасности.
5. Чужой врач не может узнать содержимое медицинской карты, даже зная UUID.
6. Предложения LLM никогда не равны подписанному врачом назначению.
7. Критические оповещения и ограничения доступа работают независимо от LLM.
8. Для разработки и демо использовать только синтетические сведения.

## Чемпионат «Клинический компас»

Отслеживаются как отдельные критерии: роли и взаимодействие врача/пациента;
клинический сценарий тревожно-депрессивных расстройств и «Авиандр»;
мониторинг симптомов и приверженности; критические уведомления;
согласование рекомендаций врачом; ссылки на медицинские источники;
законность использования опросников и шкал. Наличие пункта в плане
**не означает**, что он уже реализован или проверен.

## Известные ограничения и безопасность

⚠️ Локальная разработка **не готова** к использованию с реальными медицинскими
данными или к развёртыванию в публичном интернете. Необходимы TLS,
секреты и ключи, аудит операций, защита от brute force и злоупотреблений,
внешнее защищённое файловое хранилище, антивирусное сканирование, управление
сроками хранения, резервное копирование и тесты восстановления.

Ручной сигнал без службы доставки не является уведомлением; для экстренных случаев использовать действующие каналы помощи.

Сохранение снимков в JSONB не делает чтения Context Builder транзакционно
согласованными при конкурентных изменениях; при расширении потребуется
единый согласованный срез БД и политика неизменяемого аудита.


## Исторический контроль этапа 5.5

Перед миграцией проверить `alembic current -v` и `heads`.
После неё запустить unit-тесты маршрутов, PostgreSQL-тесты (без skip),
Ruff, `alembic check` и полный pytest. В рабочей среде пользователь
подтвердил **134 зелёных теста этапа 5.4**; для 5.5 повторная проверка
требуется, она не включена в это ранее подтверждённое число.

```powershell
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini heads
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini check
python -m ruff check backend
python -m pytest backend/tests/test_safety_notification_routes_unit.py -v
$env:TEST_DATABASE_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m pytest backend/tests/test_safety_notification_routes_pg.py -v -rs
python -m pytest backend/tests -v -rs
```

Интеграция реальной доставки, проверка email/телефона, согласия
и автоматическая эскалация остаются за пределами 5.5.

## Контрольный список текущего инкремента 5.8

Доставка внешними каналами выключена. Не удалять таблицы/аудит вне
выделенной тестовой БД. Из корня AIDoctor:

```powershell
docker compose up -d postgres
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini heads
# До миграции: current=aisafe_v6_20261018; heads=aisafe_v7_20261018
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini check
python -m ruff check backend
python -m pytest backend/tests/test_safety_read_audit_unit.py -v
$env:TEST_DATABASE_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m pytest backend/tests/test_safety_read_audit_pg.py -v -rs
python -m pytest backend/tests -v -rs
```

После миграции `current` и `heads` должны показывать
`aisafe_v7_20261018`. Сохранить вывод полного pytest и количество
`SKIPPED`/предупреждений. 5.8 нельзя считать фактически проверенным
до подтверждения PostgreSQL-интеграции в рабочей среде.


## Этап 6.1 — подтверждение локальных проверок (18.10.2026)

Пользователь подтвердил: проверки этапа 6.1 зелёные в его окружении
Windows/Python 3.12/PostgreSQL. Миграция `aiextract_v1_20261018` —
предшественник 6.2. Ручные выдержки остаются **непроверенными**,
не влияют на Context Builder и не являются результатами OCR/LLM.

## Этап 6.2 — безопасная предпроверка без допуска парсера

Добавлены новые таблицы `attachment_security_reviews` и
`attachment_security_events`, отдельный API `GET .../security` для врача/
администратора и `POST .../security/precheck` только для администратора.
Проверяются метаданные, размер (до 20 МиБ), фактический SHA-256, сигнатуры,
ряд опасных свойств DOCX/ZIP и безопасная ссылка на локальный файл.
Доступ к пациенту перепроверяется; параллельные проверки сериализуются
через PostgreSQL `FOR UPDATE`. Чтение статуса и переходы аудируются.

`quarantined → prechecked_quarantined / rejected`;
`prechecked_quarantined → prechecked_quarantined / rejected`;
`rejected → rejected`. Для всех состояний **карантин активен**, а
`antivirus_status=not_scanned` и `processing_allowed=false`.
Нет AV/CDR, парсеров, OCR, LLM или автоматического медицинского анализа.
Исходный `extraction_status=quarantined` и старые API не изменяются.
Ни одна проверка 6.2 не добавляет содержимое вложения или ручные выдержки
в Context Builder; этот инвариант остаётся прежним.

Новая миграция `aiextract_v2_20261018` (после
`aiextract_v1_20261018`). Только новые и изменённые файлы находятся
в архиве инкремента; для установки заменить соответствующие пути в
локальном проекте. Подробнее: [docs/attachment_security_v2.md](docs/attachment_security_v2.md).

**Статус:** файлы 6.2 подготовлены; локальное подтверждение Windows,
PostgreSQL и всех тестов ожидается. Не приступать к 6.3 до проверки.

### Команды 6.2 для PowerShell

```powershell
.\.venv\Scripts\Activate.ps1
docker compose up -d postgres
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini heads
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini check
python -m ruff check backend
python -m pytest backend/tests/test_attachment_security_unit.py -v
# Только существующая выделенная пустая БД aidoctor_test (не production)!
$env:TEST_DATABASE_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m pytest backend/tests/test_attachment_security_pg.py -v -rs
python -m pytest backend/tests -v -rs
Remove-Item Env:TEST_DATABASE_URL
```

Если тестовой БД нет, создать отдельную `aidoctor_test` (см. документацию
6.2). Фикстура удаляет и создаёт SQL-таблицы именно этой БД; на реальной
БД тесты недопустимы. `SKIPPED` PostgreSQL-тестов не считать успехом.
Следующий **рекомендуемый** шаг: подтвердить 6.2 в Windows; затем отдельно
согласовать архитектуру реального антивирусного сканирования и CDR.
