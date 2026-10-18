# Этап 5.7 — административные follow-up для ручных Safety Alerts

## Назначение

Follow-up — **отметка для контрольного списка врача** о ручном Safety Alert,
который не подтверждён спустя 24 часа. Это **не** автоматический клинический
триаж, экстренное оповещение, реальная доставка, уведомление о прочтении или
гарантия реакции врача. Порог 24 часа выбран как техническое допущение
для локального прототипа, а не как медицинская норма/SLA.

## Контракты и владение данными

- `safety_alerts.status` — единственный источник истины о подтверждении.
  ACK не удаляет follow-up-аудит, но немедленно исключает запись из выдачи.
- `safety_notification_routes` + `DoctorPatient` + активный пациент +
  роль `doctor` определяют разрешённого получателя.
- `safety_followups` — неизменяемая запись назначения в контрольный список.
  Уникальность `(alert_id, recipient_user_id)` обеспечивает at-most-once.
- Отсутствие/отключение маршрута блокирует и создание, и чтение записей.
- Проверка права доступа выполняется в SQL при каждом чтении.
- `Outbox`, `Inbox` и `delivery_status` этапов 5.1–5.6 не изменяются.
- Медицинский текст, reason_code, приоритет, контакты и секреты не копируются
  в follow-up-таблицу или её HTTP-схему.

## Ограничение частоты

Параметры фиксированы в `services/safety_followups.py`:

- первый follow-up не ранее чем через 24 часа после создания сигнала;
- не больше одного за всё время на пару «сигнал + получатель»;
- максимум пять новых записей на врача за скользящие 24 часа;
- одна запись максимум на запуск; перебор не больше 100 кандидатов;
- при достижении лимита запись **не** создаётся, а может быть выбрана
  последующим ручным запуском после освобождения окна.

Блокировка `SafetyAlert FOR UPDATE SKIP LOCKED` синхронизирует обработку
с подтверждением `ACK`, а блокировка `User` из маршрутизации — лимиты при
параллельных исполнителях. В PostgreSQL есть дополнительный `UNIQUE` на пару.
Если записи могли быть обработаны после получения ответа API, результат
отражает состояние на момент каждого SQL-запроса, а не будущую неизменность.

## API

`GET /api/v1/safety-followups` — до 50 последних активных административных
отметок текущего врача. `401` без токена; `403` для других ролей.
Чужие записи не видны. Возвращаются только `id`, `patient_id`, `alert_id`,
`created_at`. Только чтение: удаление/ручное изменение не предусмотрены.

## Одноразовый CLI (явное включение)

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
$env:SAFETY_FOLLOWUP_SCAN_ENABLED = "true"
python -m app.workers.safety_followup_once --once
Remove-Item Env:SAFETY_FOLLOWUP_SCAN_ENABLED
Remove-Item Env:PYTHONPATH
```

CLI возвращает `created` или `empty` без идентификаторов пациента.
Настройки по умолчанию — `false`. Автоматического расписания нет.

## Миграция и проверка

Новая ревизия `aisafe_v6_20261018`, родитель `aisafe_v5_20261018`.
Добавляется только таблица `safety_followups` и индекс.
Удаление аудита downgrade запрещено.

```powershell
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini heads
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini check
python -m ruff check backend
python -m pytest backend/tests/test_safety_followups_unit.py -v
. .\scripts\postgres_test_db.ps1
python -m pytest backend/tests/test_safety_followups_pg.py -v -rs
python -m pytest backend/tests -v -rs
```

**Не считать интеграцию проверенной, если тесты отмечены `SKIPPED`.**
Не используйте этот этап с реальными пациентами без отдельного клинического
и эксплуатационного аудита; нет мониторинга гарантированной реакции.
