# AIDoctor 6.7 — локальный Demo Bridge для ChatGPT Sites (v15)

## Архитектура и гарантии

Рабочая PostgreSQL `aidoctor` и API `http://127.0.0.1:8000` **не публикуются**.
Сервис `demo_bridge` запускается отдельно на `127.0.0.1:8766`, читает
**только отдельную БД `aidoctor_demo`**, и использует настоящий
`ContextBuilder` из `backend/app/services/context_builder.py`. Учетные
данные основного FastAPI он не использует.

Скрипт `demo_bridge.seed` создаёт нужные таблицы в `aidoctor_demo`
и добавляет одного вымышленного пациента `DEMO-001` с 4 фактами.
Повторное выполнение без изменений данных идемпотентно; чужие
или повреждённые записи блокируют выдачу.

Это **не** синхронизация реальных пациентов, не перенаправление основного API и
не подключение LLM к FastAPI. Упрощённые исходные данные ограничены одним
учебным сценарием. Внешняя модель работает внутри ChatGPT Plus.
Никакая клиническая запись обратно в AIDoctor не выполняется.

## 1. Настройка Windows / PowerShell

Из корня проекта после копирования полных файлов ZIP:

```powershell
docker compose up -d postgres
docker compose exec postgres psql -U aidoctor -d postgres -c "CREATE DATABASE aidoctor_demo OWNER aidoctor;"
```

Команда CREATE DATABASE выполняется **только один раз**. Если база уже создана,
не выполняйте её снова. Не используйте `aidoctor`, `aidoctor_test` или
иную рабочую БД. Имя `aidoctor_demo` в коде жёстко закреплено.

Создайте переменные **в текущем окне PowerShell** (пример пароля соответствует
типовой локальной конфигурации проекта; при других реквизитах замените):

```powershell
$env:PYTHONPATH = (Resolve-Path .\backend).Path
$env:AIDOCTOR_DEMO_DB_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_demo"

python -m demo_bridge.seed
python -m uvicorn demo_bridge.server:create_app --factory --host 127.0.0.1 --port 8766
```

Оставьте окно с uvicorn работающим. В другом окне:

```powershell
Invoke-RestMethod http://127.0.0.1:8766/health
Invoke-RestMethod http://127.0.0.1:8766/demo/v1/patient | ConvertTo-Json -Depth 10
Invoke-RestMethod http://127.0.0.1:8766/demo/v1/context | ConvertTo-Json -Depth 20
Invoke-WebRequest http://127.0.0.1:8766/openapi.json
```

Если `seed` не проходит, **не меняйте имя БД на рабочее**. Сначала проверьте
лог PostgreSQL и существование чистой базы `aidoctor_demo`.

## 2. Только после успешной проверки — HTTPS

В отдельном окне PowerShell:

```powershell
ngrok http 8766
```

Если ngrok ещё не настроен, потребуется учётная запись и конфигурация
токена согласно документации ngrok. Скопируйте HTTPS-адрес из вывода
(пример `https://example.ngrok-free.app` — **не настоящий адрес**).

Проверьте вручную:

```powershell
Invoke-RestMethod https://ВАШ-HTTPS-ДОМЕН/health
Invoke-RestMethod https://ВАШ-HTTPS-ДОМЕН/demo/v1/context
```

Никогда не создавайте `ngrok http 8000`: это основной медицинский backend.
При завершении демонстрации остановите uvicorn и ngrok (`Ctrl+C`).
Публичный адрес временный, и он может меняться.

**Авторизация:** на трёх read-only маршрутах не требуется. Это допускается
исключительно потому, что `aidoctor_demo` — отдельная база с фиксированным
синтетическим примером. По публичному адресу их сможет вызвать любой,
поэтому не добавляйте реальные медицинские данные даже в demo DB.
Используйте временный туннель и не оставляйте его открытым.

## 3. HTTP и JSON-контракт Site Creator

- `GET https://ВАШ-HTTPS-ДОМЕН/health` — `{"status":"ok","synthetic":true,"read_only":true}`.
- `GET https://ВАШ-HTTPS-ДОМЕН/demo/v1/patient` — инструмент `get_demo_patient`.
- `GET https://ВАШ-HTTPS-ДОМЕН/demo/v1/context` — инструмент `get_demo_context`.
- `GET https://ВАШ-HTTPS-ДОМЕН/openapi.json` — актуальная OpenAPI 3.x схема.
- Авторизация: нет; только синтетические данные.
- Другие URL / методы: 404 / 405, без записи.
- При ошибке/подмене/отключении БД: HTTP 503; нельзя возвращать кешированный
  или встроенный fallback как будто ответ пришёл из Bridge.

Пример обёртки ответов (поле `data` отличается):

```json
{
  "schema_version": "1.0",
  "synthetic": true,
  "mode": "synthetic_demo_only",
  "source": "aidoctor_context_builder_demo_db",
  "clinical_processing_allowed": false,
  "data": {"demo_id": "DEMO-001", "synthetic": true},
  "content_sha256": "<64 hex>"
}
```

`content_sha256` вычисляется по **полю `data` и только ему**:

```python
import hashlib
import json

digest = hashlib.sha256(
    json.dumps(
        response["data"],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
).hexdigest()
```

Внутри `data.clinical_context.content_sha256` находится **другой хеш**,
вычисленный самим Context Builder по `schema_version`, `patient_id`,
`items`, `truncated_sources`, `excluded_attachments_count` без
`generated_at`. Нельзя сравнивать эти два SHA-256 друг с другом.

Site должен выполнять **серверный HTTP GET** к Bridge. Секретов в
браузерном JS нет. Если платформа Sites не позволяет серверный fetch
к вашему домену, **не имитируйте успешное подключение** — сообщите,
что внешние вызовы заблокированы, и передайте ошибку для диагностики.

Сохранить имена MCP-инструментов без изменения контрактов плагина:
`get_demo_patient`, `get_demo_context`. Каждый инструмент вызывает один
соответствующий GET. Допустимо вернуть всю обёртку JSON как есть.

## 4. Проверки

```powershell
python -m ruff check backend demo_bridge
python -m pytest backend/tests/test_demo_bridge_unit.py -v -rs

$env:TEST_DATABASE_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m pytest backend/tests/test_demo_bridge_pg.py -v -rs
python -m pytest backend/tests -v -rs
Remove-Item Env:TEST_DATABASE_URL

python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini check
```

ВНИМАНИЕ: PostgreSQL-тесты пересоздают таблицы выделенной `aidoctor_test`.
Они не используют `aidoctor_demo`. Изолированная демонстрационная БД
создаётся отдельно скриптом seed, миграций для неё нет.

## 5. Границы безопасности и дальнейший вариант

Сейчас — **бюджетно**: локальный Context Builder, отдельная синтетическая
PostgreSQL, временный HTTPS-туннель, существующий ChatGPT Site/MCP и
подписка Plus. Программного LLM endpoint для FastAPI нет. Отчёт
остаётся внутри ChatGPT, анализ не является медицинским заключением.

Для настоящего продукта — **быстрее в эксплуатации и контролируемее**:
FastAPI LLM Gateway → официальный OpenAI API с лимитами →
структурированный черновик в PostgreSQL → подтверждение врачом
(этап 7) → аудит и наблюдаемость. Это потребует отдельных расходов,
юридических и технических мер для реальных медицинских данных.

### Критерии готовности

1. `seed` успешно создаёт ровно одного вымышленного пациента.
2. `GET /health`, `/patient`, `/context` возвращают 200; оба `synthetic=true`.
3. Хеш ответа сверяется с каноническим JSON `data`.
4. Чужой пациент, отсутствие метки synthetic, добавленное вложение
   либо ошибка БД приводят к 503.
5. Реальный Site вызывает оба MCP-инструмента и получает данные
   именно `source: aidoctor_context_builder_demo_db`.
6. Ни основной `aidoctor`, ни каталог вложений не экспортируются через туннель.

Проверенная при сборке статическая OpenAPI-схема: `docs/demo_bridge_openapi_v15.json`.
