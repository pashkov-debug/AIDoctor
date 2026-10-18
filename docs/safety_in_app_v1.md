# Этап 5.6 — локальная доставка Safety Alerts во внутренний inbox

## Назначение и границы

5.6 подключает уже существующие PostgreSQL Outbox (5.2), worker (5.4) и
подтверждённые in_app-маршруты врача (5.5). Внешние каналы отсутствуют.
Запись в `safety_in_app_notifications` — **технически подтверждённая
доставка во внутреннее хранилище**, а НЕ прочтение врачом.

Транспорт `InAppTransport` не вызывает сеть и не сохраняет медицинский
текст, диагноз, телефон, email, payload или секреты. Он использует только
ID события, пациента, получателя, маршрута и сигнала. Для ознакомления
врач открывает существующий защищённый API сигналов пациента.

## Источники истины

- `safety_alerts` — клиническое событие, не меняется;
- `safety_outbox` — очередь/lease/retries и аудит завершения;
- `safety_notification_routes` + `DoctorPatient` + `User` + `Patient` —
  актуальное право доставки в учётную запись врача;
- `safety_in_app_notifications` — зафиксированный факт записи в inbox.
  `UNIQUE(outbox_id, recipient_user_id)` предотвращает дубли
  после падения между commit в inbox и фиксацией Outbox.

Резервирование и запись в inbox — разные транзакции. Адаптер
проверяет `processing`, число попытки, актуальный lease и связь с alert,
затем получает разрешённые маршруты с блокировками. Записи inbox
коммитятся **до** `mark_delivered`. При повторе вставки дедуплицируются.

Нет eligible-маршрута → `route_unavailable`, Outbox планирует повтор по
правилам 5.2 (максимум 3 попытки). Появившийся маршрут не воскресит
автоматически запись со статусом `failed`. Автоматической эскалации нет.

## API

`GET /api/v1/safety-inbox` — последние 50 уведомлений
**только авторизованного врача** с действующей связью DoctorPatient
и неудалённым пациентом. Возвращаются:
`id`, `patient_id`, `alert_id`, `created_at`.

Для другой роли — `403`, без bearer — `401`, для врача без уведомлений —
`[]`. Никакого API чужого inbox или удаления нет. Отключение маршрута
блокирует **новую** доставку; прежние записи остаются видны врачу до
отзыва доступа к пациенту. Отзыв DoctorPatient и soft-delete пациента
скрывают их немедленно при чтении.

`delivery_status` прежнего Safety Alerts API остаётся
`not_configured` — он исторически не показывает факт in_app-записи.
Используйте новый inbox, не интерпретируйте это поле как статус in_app.

## Включение (Windows PowerShell)

Два независимых условия: явная серверная настройка
`SAFETY_IN_APP_DELIVERY_ENABLED=true` и разовый CLI `--once`.
По умолчанию значение `false`; обычный запуск backend, Docker или
`app.workers.safety_outbox --status` ничего не отправляет.

Перед первой доставкой врач должен включить собственную настройку
через `PUT /api/v1/patients/{id}/safety-notification-route`
с `{"enabled":true,"channel":"in_app"}`.

```powershell
# Выполнить только после успешной миграции и проверки маршрутов.
$env:PYTHONPATH = (Resolve-Path .\backend).Path
$env:SAFETY_IN_APP_DELIVERY_ENABLED = "true"
python -m app.workers.safety_in_app_once --once
Remove-Item Env:SAFETY_IN_APP_DELIVERY_ENABLED
Remove-Item Env:PYTHONPATH
```

Каждый вызов CLI обрабатывает максимум одну запись Outbox.
Расписание, бесконечный цикл, сторонний провайдер, почта/SMS/push и
автоматическая отправка **не добавлены**.

## Тесты и миграции

```powershell
docker compose up -d postgres
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini heads
# До upgrade: current = aisafe_v4_20261018, heads = aisafe_v5_20261018
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini check

python -m ruff check backend
python -m pytest backend/tests/test_safety_in_app_unit.py -v
. .\scripts\postgres_test_db.ps1
python -m pytest backend/tests/test_safety_in_app_pg.py -v -rs
python -m pytest backend/tests -v -rs
```

`TEST_DATABASE_URL` обязан указывать на выделенную локальную `*_test` БД:
существующая фикстура **удаляет схему** до и после тестов. Не запускать
интеграционные тесты на рабочей БД. Новая ревизия Alembic:
`aisafe_v5_20261018` после `aisafe_v4_20261018`. Downgrade запрещён,
поскольку удалил бы историю внутренних доставок.

## Контрактные и операционные риски

1. Доказана только **одна запись в inbox на получателя и событие**
   (при сохранности БД). Exactly-once за пределами PostgreSQL не обещается.
2. Блокировка маршрута/связи защищает решение о получателе в транзакции.
   Уже созданное уведомление при последующем выключении настройки остаётся,
   пока врач имеет доступ к пациенту.
3. При краше между фиксациями inbox и Outbox запись может быть видима,
   хотя статус Outbox ещё `processing`/`pending`; следующая попытка
   исправляет состояние без дубля.
4. API пока не предоставляет unread/read и аудит чтения — этап 5.8.
5. Шифрование, retention, управление ключами, уведомления real-time и
   соответствие нормативным требованиям остаются вне 5.6.
