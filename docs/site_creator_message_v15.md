# Готовое задание для ChatGPT Site Creator

Используйте **после** запуска Bridge и получения фактического HTTPS домена
из `ngrok http 8766`. Подставьте один и тот же адрес во все URL.

---
Обнови уже существующий AIDoctor Demo Site. Ничего не меняй в клинических
skills плагина «Для Тани».

Сохрани имена MCP-инструментов: `get_demo_patient`, `get_demo_context`.
Теперь они должны получать JSON **серверным GET** с отдельного HTTP
AIDoctor Demo Bridge.

Base URL: https://ЗАМЕНИТЬ-НА-РЕАЛЬНЫЙ-ДОМЕН
GET /health
GET /demo/v1/patient -> get_demo_patient
GET /demo/v1/context -> get_demo_context
GET /openapi.json -> OpenAPI схема
При необходимости используй прилагаемый demo_bridge_openapi_v15.json.

Метод авторизации: отсутствует, поскольку здесь только отдельные
синтетические данные. Никаких токенов, cookie, запросов к PostgreSQL,
рабочему FastAPI или файловому хранилищу.

Контракт каждого ответа:
- schema_version = "1.0"
- synthetic = true
- mode = "synthetic_demo_only"
- source = "aidoctor_context_builder_demo_db"
- clinical_processing_allowed = false
- data = JSON object
- content_sha256 = lowercase SHA-256 hex по JSON `data`, сериализация
  сортировка ключей, UTF-8, без ASCII escape, без пробелов (разделители
  "," и ":"). Проверять хеш **после декодирования JSON**.
- У контекста внутри `data.clinical_context.content_sha256` есть
  собственный хеш Context Builder — это не хеш обёртки.

Сначала проверь `/health`, затем оба инструмента.
Если HTTP не 200, неверная схема, synthetic не true, не совпал хеш
или удалённый источник недоступен: возвращай явную ошибку. НЕ
подставляй ранее встроенного пациента как будто это данные Bridge.
Не используй кеш и не раскрывай медицинские данные в логах.

Не создавай инструменты записи. Не меняй старые skills.
Перед повторной публикацией покажи результат вызова обоих
инструментов и использованные URL. Только после моей команды публикуй.
---

Ограничение: если хостинг Site не разрешает server-to-server HTTP GET
к внешнему URL, сообщи об этом и не имитируй успешную интеграцию.
