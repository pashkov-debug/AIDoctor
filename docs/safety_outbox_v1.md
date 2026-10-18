# AIDoctor — этап 5.2: PostgreSQL Outbox (без отправки)

## Границы инкремента

Исходный код: `master` и архив проекта с этапом 5.1.
Ревизия: `aisafe_v2_20261018`, `down_revision = aisafe_v1_20261017`.

Сохранены действующие маршруты `/api/v1/patients/{patient_id}/safety-alerts`
и константа ответа `delivery_status = "not_configured"`.
Это **не подтверждение доставки**. Отсутствуют worker, планировщик,
почта, SMS, push, эскалация и автоматическое создание клинических тревог.

## Данные и транзакции

- `safety_alerts` остаётся источником состояния клинического сигнала.
- `safety_alert_events` остаётся источником аудита врачебных действий.
- `safety_outbox` содержит событие `created` для одного `safety_alerts.id`.
  Уникальность `(alert_id, event_type)` обеспечивает дедупликацию *события*.
- `safety_outbox_events` содержит `enqueued`, `claimed`, `retry_scheduled`,
  `delivered`, `exhausted`. Хранятся только коды технических ошибок, не текст
  исключения, медицинские данные или сообщение получателю.
- Создание сигнала, клинического события `created`, Outbox и записи `enqueued`
  выполняется **одной PostgreSQL-транзакцией**. При ошибке всё откатывается.
- На этапе 5.2 HTTP POST **не был идемпотентен**: повторный POST создавал
  новый сигнал. С этапа 5.3 появился необязательный `Idempotency-Key`:
  [safety_idempotency_v1.md](safety_idempotency_v1.md). Без этого заголовка
  повтор по-прежнему создаёт новый сигнал.

## Машина состояний

| Из | Операция | В |
|---|---|---|
| — | `enqueue_alert_created(session, alert_id)` | `pending` |
| `pending` (по времени) | `claim_due()` | `processing` |
| `processing` | `mark_attempt_failed()` | `pending` или `failed` |
| `processing` (lease истёк) | `claim_due()` выполняет recovery | `pending` или `failed` |
| `processing` | `mark_delivered()` | `delivered` |

Одна попытка резервируется не более чем на 300 секунд по умолчанию.
Резервирование выдаёт новый случайный токен. Завершить попытку можно только
при совпадении токена, номера попытки, сущности и неистёкшем lease.
`claim_due` использует `FOR UPDATE SKIP LOCKED`, чтобы несколько будущих worker
не брали одновременно одну запись. `claim_due`, `mark_attempt_failed` и
`mark_delivered` сами завершают транзакцию: им требуется **отдельная Session**
worker, не Session активного HTTP-запроса.

Максимум три попытки, паузы перед повтором 30 и 60 секунд;
третья ошибка переводит запись в `failed`. Восстановление просроченного
lease учитывается как неудачная попытка, с кодом `lease_expired`.
Recovery происходит только при вызове `claim_due`, **не автоматически**.

`mark_delivered` написана для интеграции с будущим адаптером и тестируется
с имитацией подтверждения. **Не вызывайте её без достоверного подтверждения
от внешнего канала**. Даже при этом семантика внешнего подтверждения может
означать принятие провайдером, а не прочтение пользователем.

## Последовательность применения в PowerShell (корень проекта)

Проверить текущую БД *до изменения*:

```powershell
docker compose up -d postgres
python -m alembic -c alembic.ini heads
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini history -v
```

**Ожидание при полностью завершённом этапе 5.1:**
`current = aisafe_v1_20261017`, `heads = aisafe_v2_20261018`
(после добавления файлов). Если `current` другой, сначала выяснить причину.
Это ожидание, а не фактическое утверждение о вашей БД.

После проверки:

```powershell
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini check
python -m ruff check backend
python -m pytest backend\tests\test_safety_outbox_unit.py -v
python -m pytest backend\tests\test_safety_outbox_pg.py -v -rs
python -m pytest backend\tests -v -rs
```

Отдельная `aidoctor_test` должна существовать и `TEST_DATABASE_URL` должна
быть задана в той же PowerShell-сессии. `scripts/postgres_test_db.ps1`
создаёт тестовую БД и выставляет переменную в своей области выполнения:
при необходимости выполните `. .\scripts\postgres_test_db.ps1`
(с точкой и пробелом в начале). Тестовый fixture **очищает `*_test` БД**.
Убедитесь, что там нет важных данных.

`alembic check` полезен, но не заменяет миграцию и интеграционные тесты.
Ревизии безопасности запрещают `downgrade`, журнал не является
криптографически защищённым от администратора БД.

## Что не реализовано

Нет рабочего диспетчера, конфигурации каналов, автоматической рассылки,
управления получателями, клинических сценариев эскалации, SLA
и гарантий exactly-once у внешних
провайдеров. Возможны повторы внешнего запроса при crash после отправки,
но до `mark_delivered`; будущему адаптеру понадобится идемпотентность
со стороны провайдера или устойчивая стратегия дедупликации.
Не использовать как систему экстренной помощи.
