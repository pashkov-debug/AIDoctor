# AIDoctor — этап 5.4: изолированный исполнитель Outbox

## Цель и границы

Существует библиотечный однократный исполнитель `app.workers.safety_outbox.process_one`
с контрактом `DeliveryTransport.send(DeliveryEnvelope) -> DeliveryReceipt`.
Синхронная обработка: **одна запись за вызов**, с отдельной SQLAlchemy `Session`
на claim и на завершение. Внешний вызов происходит строго между двумя commit
и без открытой Session, удерживающей блокировку. В данной версии нет ни
реального транспорта, ни адресов получателей, ни SMTP/SMS/push,
ни фонового запуска, ни планировщика.

**Не включайте отправку на реальных пациентов.** Тестовый транспорт
применён только в тестах. В обычном CLI можно лишь посмотреть агрегированные
статусы; по умолчанию CLI не умеет запускать отправку.

## Контракт

- `DeliveryEnvelope`: `outbox_id`, `alert_id`, `event_type`, `attempt_number`.
  Не содержит медицинских текстов и получателей, но идентификаторы
  **всё равно не следует публиковать** во внешние журналы.
- `DeliveryTransport`: протокол `send(envelope)`, реализация только после
  явного выбора канала, адресации, согласия, ключей и безопасности.
- `DeliveryReceipt(confirmation_id="...")`: адаптер возвращает **только
  достоверное подтверждение**, допускаемое существующим контрактом
  `mark_delivered`. Не возвращайте такой объект для «принято локально»,
  таймаута, отсутствия маршрута или неподтверждённой отправки.
- `TransportFailure(code)`: коды `provider_unavailable`, `provider_timeout`,
  `provider_rejected`, `route_unavailable`; остальные необработанные
  исключения записываются как `transport_unexpected` без текста исключения.
- `None` вместо транспорта: выбрасывается `TransportNotConfigured`
  **до обращения к PostgreSQL**, не происходит ни резервирования,
  ни списания попытки.
- Пустое/невалидное подтверждение: `unconfirmed_delivery`, попытка
  не отмечается успешно.
- После третьей неудачи статус в БД `failed` (в результате `process_one`
  также возвращается `failed`).
- Просроченный/заменённый claim не подтверждается. Возможен повтор внешнего
  действия после истечения lease, если провайдер не поддерживает дедупликацию.

События `claimed`, `retry_scheduled`, `exhausted`, `delivered` записываются
существующим сервисом `app.services.safety_outbox`; таблицы и API не меняются.
Отсутствует запись confirmation_id в БД: это **ещё не полноценный аудит
доказательств доставки** и не гарантия прочтения адресатом.
`delivery_status: not_configured` в ответе API не меняется.

## Безопасная диагностика

PowerShell в корне репозитория:

```powershell
.\.venv\Scripts\Activate.ps1
docker compose up -d postgres
$env:PYTHONPATH = (Resolve-Path .\backend).Path
python -m app.workers.safety_outbox --status
Remove-Item Env:PYTHONPATH
```

Результат: `pending`, `processing`, `delivered`, `failed` и числа.
Запрос только `SELECT COUNT(...) GROUP BY status`, без `claim_due`,
подтверждения, пересчёта дат или изменения записей.
Отсутствие `--status` приводит к справке и ненулевому коду завершения.

## Проверка после замены файлов

```powershell
python -m ruff check backend
python -m pytest backend/tests/test_safety_worker_unit.py -v
. .\scripts\postgres_test_db.ps1
python -m pytest backend/tests/test_safety_worker_pg.py -v -rs
python -m pytest backend/tests -v -rs
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini heads
python -m alembic -c alembic.ini check
```

Для 5.4 нет новой миграции, `heads` остаётся `aisafe_v3_20261018`.
До работы с 5.4 нужно завершить установку и тесты 5.3.
PostgreSQL-тесты используют только выделенную БД `*_test`;
fixture удаляет её таблицы. `SKIPPED` не означает успешную интеграцию.

## Ограничения и последующие шаги

- Транспорт должен иметь собственный короткий таймаут **меньше lease**
  и внешний идемпотентный ключ `outbox_id`; без этого возможны дубли
  при crash после сетевого запроса, до фиксации результата.
- Событие `delivered` по текущей схеме означает лишь подтверждение
  транспорта, а не фактическое прочтение врачом.
- До следующего этапа необходим выбор проверенного адресата,
  канала доставки, сохранение подтверждения провайдера, опциональное
  шифрование, юридические основания обработки и отдельное включение.
- Нельзя использовать как экстренную службу или при работе с реальными
  медицинскими данными без аудита.
