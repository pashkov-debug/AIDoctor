# UI-1C — кабинет администратора (23.10.2026)

Реализация поверх **UI-1B**, установленного после **UI-1A**. Применяется
к существующей локальной PostgreSQL `aidoctor`, созданные синтетические
карточки сохраняются между запусками. Медицинские данные не используются.

## Реализовано

- Вход существующего администратора `/app`, входные роли `doctor`, `patient`, `admin`.
- `GET /api/v1/admin/users`: до 500 пользователей, без паролей и их хешей.
- `POST /api/v1/admin/users`: новый врач или пациент; пароль >= 12 символов,
  хеширование уже существующим `hash_password`, логин уникален, ответ 409 при дубле.
  Создание других администраторов и изменение роли запрещены через UI-1C.
- `GET /api/v1/admin/patients`: до 500 активных карточек; возвращаются
  только идентификатор, псевдоним, признак `synthetic`, ID владельца аккаунта.
- `POST /api/v1/admin/synthetic-patients`: создание учебной карточки с
  `demographics_json.synthetic=true`, без повторного заполнения при старте.
- `GET /api/v1/admin/links`: до 500 действующих связей врач–пациент.
- Существующий `POST /api/v1/access/link`: безопасная идемпотентная связь,
  без назначения пациента удалённой карточке, журналируемая.
- `DELETE /api/v1/admin/links/{link_id}`: отзыв права врача, 404 если связи нет.
- Существующий `POST /api/v1/access/patient-account`: идемпотентная привязка,
  теперь **нельзя** молча заменить уже привязанный аккаунт; 409, если карточка
  уже связана с другим пользователем или аккаунт занят.
- `GET /api/v1/admin/audit`: последние 50 зафиксированных событий
  **административных изменений UI-1C**. Старые события до установки
  миграции не восстанавливаются. Не является полным security audit системы.
- Отдельная таблица `admin_audit_events`, одна транзакция с изменением.

Все API защищены backend-ролью `admin`; авторизация в браузере
использует текущий Bearer-токен в памяти вкладки. Нет локального хранения
токена и нет сторонних JS-библиотек.

## Установка и запуск Windows PowerShell

Распакуйте ZIP **поверх уже установленного UI-1B**, оставив остальные
файлы проекта. ZIP содержит только новые/заменяемые файлы, полный
`README.md` и этот документ. Ничего не удаляйте из `aidoctor`.

```powershell
# Из корня AIDoctor, активна .venv
docker compose up -d postgres
docker compose exec postgres pg_isready -U aidoctor -d aidoctor

python -m alembic -c alembic.ini current
python -m alembic -c alembic.ini heads
# Ожидаемый head исходников: ui1c_20261023
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini check

python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

Адрес: http://127.0.0.1:8000/app. Вход: `admin_ui1`
с паролем, созданным ранее. Если этой учётной записи нет, одноразово:

```powershell
$env:PYTHONPATH = "backend"
python -m backend.scripts.create_user admin_ui1 admin
Remove-Item Env:PYTHONPATH
```

После UI-1C можно создавать врачей и пациентов через интерфейс; CLI
для них больше не обязателен.

## Тесты — выполнять из корня проекта

Статические, не должны очищать базу:

```powershell
python -m ruff check backend
python -m ruff format --check backend
python -m pytest backend/tests/test_ui1_unit.py backend/tests/test_ui1b_unit.py backend/tests/test_ui1c_unit.py -v
python -m alembic -c alembic.ini check
```

**Только отдельная тестовая БД**, не `aidoctor`! Фикстура
`pg_engine` выполняет `drop_all()` и `create_all()`:

```powershell
# Один раз создать выделенную БД, если её нет:
docker compose exec postgres psql -U aidoctor -d postgres -c "CREATE DATABASE aidoctor_test;"
# Если уже существует, ошибка CREATE DATABASE не требует повторных попыток.

$env:TEST_DATABASE_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m pytest backend/tests/test_ui1_pg.py backend/tests/test_ui1b_pg.py backend/tests/test_ui1c_pg.py -v -rs
python -m pytest backend/tests -v -rs
Remove-Item Env:TEST_DATABASE_URL
```

Не засчитывайте `SKIPPED` как успешный PostgreSQL-тест.
Проверка миграции `upgrade head` — на локальной дев-БД, **без**
удаления таблиц.

## Контракты и конфликты

- **Владение данными:** `users`, `patients.user_id`, `doctor_patients`
  являются источниками истины; frontend — только запросы, без клинических решений.
  Аудит создаётся транзакционно с каждым новым административным изменением.
- **Совместимость:** маршруты `POST /access/link` и
  `POST /access/patient-account` сохранены. Новый отказ 409 при попытке
  переназначить занятую карточку — целенаправленная защита инварианта.
  Врачебные/пациентские маршруты и `doctor_context` без изменений.
- **Эволюция:** новые административные операции расширяются через
  отдельные endpoint/service и аудит; привязки не должны создаваться
  вне server-side ACL.

## Границы ответственности и риски

Нет изменения/блокировки ролей существующих пользователей, смены паролей
через UI, пересоздания БД, удаления пациентов, редактирования реальных
медицинских карт, экспорта аудита и полного администрирования Safety Alerts.
История административных действий, сделанных до UI-1C, не реконструируется.
Доступ к старым клиническим API пока требует самостоятельного privacy-review.

В UI-1C список ограничен 500 записями и без пагинации: только локальный
этап разработки. Пароль передаётся по HTTP внутри loopback-соединения —
на внешней машине требуется TLS и отдельный security-review.

**Не направлять на production / реальные данные пациентов.**
При условии успешных локальных тестов UI-1C завершает базовый каркас
трёх кабинетов; следующие этапы — клиническая карточка врача и контролируемая
публикация утверждённых решений.
