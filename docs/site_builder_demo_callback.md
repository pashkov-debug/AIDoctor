# AI-1: обратный канал Site Builder → AIDoctor (только синтетический пилот)

## Назначение

Это **не** запуск модели из кнопки AIDoctor. Анализ выполняется в чате ChatGPT
через уже существующий Site и его MCP-инструменты чтения. Новый write-инструмент
`submit_demo_analysis` должен вызывать серверный обработчик Site, а он — API
AIDoctor. Обработчик Site пока не реализован в этом репозитории.

Входящий результат остаётся **отдельным информационным черновиком**.
Он не становится `ClinicalOrder`, не вызывает `/review/approve`, не меняет
`AIRequest.status` и не публикуется пациенту.

## Подтверждённые маршруты

**Базовый HTTPS URL текущего демонстрационного сервера:**
`https://185-200-179-238.sslip.io`

1. **Чтение клинического контекста (уже есть):**

   `GET /api/v1/patients/{patient_id}/ai-requests/{request_id}/agent-context`

   `Authorization: Bearer <врачебная-сессия>`; необходимо право врача на
   конкретного пациента. Ответ: `ai_agent_context.v1`. Включает
   `patient_context`, `doctor_context`, `orders_review`, `orders_sha256`,
   `request_id`, `patient_id` и вопрос врача. Срок жизни существующей
   сессии — 8 часов. Это НЕ утверждение о том, как реализованы два
   текущих read-инструмента Site. Их обработчики нужно проверить отдельно.

2. **Приём результата (добавляется этим инкрементом):**

   `POST /api/v1/integrations/site-builder/demo-analyses`

   `Content-Type: application/json`
   `X-AIDoctor-Bridge-Token: <секрет-из-настроек-Site>`

   `201 Created` при первом приёме. Повтор идентичного JSON идемпотентен.
   `401` — неверный ключ, `404` — канал выключен или запрос отсутствует,
   `403` — не синтетический пациент / не `doctor_ui1`,
   `409` — неверный SHA, устаревший контекст или другой анализ уже сохранён,
   `422` — схема нарушена.

3. **Просмотр врачом (добавляется этим инкрементом):**

   `GET /api/v1/patients/{patient_id}/ai-requests/{request_id}/demo-analysis`

   Стандартный Bearer-токен врача (не Bridge Token). В кабинете врача
   появится кнопка «Посмотреть черновик AI-анализа» возле запроса.

**НЕ существует** автономного вызова модели из FastAPI. Нельзя выдавать
этот маршрут за LLM Gateway, MCP-сервер AIDoctor или прямую интеграцию
ChatGPT Plus через OpenAI API.

## Правила контрольных сумм

`context_sha256` — не хеш всего JSON ответа `agent-context` и не хеш его
текстового представления. Значение берётся из исходного AI-запроса
`AIRequest.context_sha256` (то же значение
`patient_context.content_sha256`). Его сформировал
`calculate_content_sha256()` из `backend/app/services/context_delta.py`:

```python
canonical = json.dumps(
    {
        "schema_version": context.schema_version,
        "patient_id": context.patient_id,
        "items": [item.model_dump(mode="json", exclude_none=False) for item in context.items],
        "truncated_sources": context.truncated_sources,
        "excluded_attachments_count": context.excluded_attachments_count,
    },
    sort_keys=True,
    ensure_ascii=False,
    separators=(",", ":"),
).encode("utf-8")
context_sha256 = hashlib.sha256(canonical).hexdigest()
```

`generated_at` и само `content_sha256` в хеш не входят. Нельзя
пересериализовать данные в JavaScript и предполагать побайтовое совпадение;
**лучше передать неизменённое значение из API** и сверить его сервером.

`orders_sha256` — отдельный SHA-256 от *полного* валидированного
`orders_review`, включая `approved_orders` и `proposed_orders_for_review`.
Правило: `json.dumps(payload, sort_keys=True, ensure_ascii=False,
separators=(",", ":"), allow_nan=False).encode("utf-8")`; именно так
работает `review_hash()` в `backend/app/services/ai_agent_context.py`.
Передавать полученное в API `orders_sha256`, не придумывая своё.

**Важно:** SHA-256 подтверждает совпадение данных, но не личность агента.
Авторизацию обеспечивает секрет обратного канала. На приёме также
проверяется актуальность контекста и назначений.

## Схема `aidoctor_demo_analysis.v1`

Все поля верхнего уровня обязательны, кроме массивов (могут отсутствовать
или быть пустыми). Неизвестные поля отвергаются.

```json
{
  "schema_version": "aidoctor_demo_analysis.v1",
  "request_id": "00000000-0000-4000-8000-000000000001",
  "patient_id": "00000000-0000-4000-8000-000000000002",
  "context_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "orders_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "status": "draft_requires_review",
  "summary": "Учебный предварительный разбор предоставленного синтетического случая. Требует независимой проверки врачом.",
  "hypotheses": [
    {"title": "Гипотеза", "rationale": "Описание допущений и аргументов без окончательного диагноза.", "confidence": "uncertain"}
  ],
  "medication_risks": [
    {"medication": "Название препарата из контекста", "risk": "Описание потенциального риска и необходимых уточнений.", "severity": "unknown"}
  ],
  "missing_information": ["Уточнить сведения о ранее принимаемых препаратах"],
  "suggested_examinations": [
    {"name": "Предлагаемая проверка", "rationale": "Почему она может быть полезна в данном учебном случае"}
  ],
  "sources": [
    {
      "title": "Проверяемый источник",
      "url": "https://pubmed.ncbi.nlm.nih.gov/",
      "relevance": "Требует проверки применимости и соответствия утверждениям"
    }
  ],
  "limitations": ["Модель не подтверждала правильность дозировок внешними базами"]
}
```

В примере указаны **фиктивные UUID и SHA**, они не подойдут для настоящего
вызова. Использовать идентификаторы из текущего API. Медицинские выводы
выше не являются рекомендациями пациенту.

### Как добавить инструмент в существующий Site

Создать write-инструмент **`submit_demo_analysis`**, не меняя существующие
два инструмента чтения. Серверный обработчик Site должен:

1. Получить разрешённый контекст через действующие read-инструменты.
2. Передать агенту разделённые `patient_context`, `doctor_context`,
   `orders_review` и вопрос врача.
3. Получить только JSON из схемы `aidoctor_demo_analysis.v1`.
4. Проверить JSON и отправить HTTPS POST в AIDoctor **с сервера Site**.
5. Доставать секрет из приватного хранилища Site, не вставлять его
   в опубликованный JS, чат, GitHub, логи или URL.
6. При `201` показать подтверждение с `request_id`; при
   `401/403/409/422` показать код ошибки и не повторять без изменений.
7. Никогда не вызывать `/review/approve`, endpoints назначений или
   автоматический импорт лекарственных назначений.

Site Builder **ещё должен подтвердить**, что его серверный обработчик
может хранить секрет и выполнять внешний HTTPS POST. Без этого публикацию
инструмента и проверку двустороннего обмена считать незавершёнными.

## Включение на VDS после успешного Commit → Push

**По умолчанию приём выключен.** В работающем репозитории на VDS
`/opt/aidoctor/git-checkout/.env.test` хранится вне Git. Добавить
следующие значения **только там**:

```env
AIDOCTOR_DEMO_CALLBACK_ENABLED=1
AIDOCTOR_SITE_BRIDGE_TOKEN=<случайный_urlsafe_секрет_от_40_символов>
```

Для генерации выполнить `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`
**локально на VDS**. Никогда не копировать настоящий секрет в чат, архив,
GitHub или README. Разрешения `.env.test`: `0600`.

Обновить приложение с новой конфигурацией:

```bash
cd /opt/aidoctor/git-checkout
docker compose --env-file .env.test -f deploy/compose.test.yaml up -d --no-deps --wait app
```

Не делать `down -v`, не повторять seed и не восстанавливать БД без
отдельного решения.

## Тестирование

В PowerShell PyCharm после установки архива:

```powershell
python -m ruff check backend
python -m ruff format --check backend
node --check backend/app/web/assets/app.js
python -m pytest backend/tests/test_site_builder_demo_bridge_unit.py -q
```

Полный тестовый PostgreSQL-прогон проводить **только в aidoctor_test**,
не на основной локальной БД и не в действующей серверной БД.

Первый внешний тест: один новый `AIRequest` от `doctor_ui1` для
синтетического пациента, вывод доступного `agent-context`, отправка
структурированного анализа и проверка кнопки просмотра в кабинете врача.

Отрицательные сценарии: неверный Bridge Token (`401`), другой врач/
не синтетический пациент (`403`), старый SHA (`409`), повтор того же
JSON (идемпотентно), иной JSON для того же запроса (`409`), попытка
прямого доступа пациента к просмотру (отказ).

## Границы ответственности

- Новая таблица `ai_demo_analyses` не входит в clinical_orders.
- Никаких новых API для утверждения лекарств не создаётся.
- Источники проверяются на наличие полей и правильный синтаксис URL,
  **не** на существование публикации, DOI или достоверность содержания.
- ChatGPT Plus не заменяет API-токен поставщика модели.
- Работа с реальными пациентами категорически отключена.
- Публичный адрес `sslip.io` — временный для демонстрации.
