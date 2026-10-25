# AIDoctor — независимая сверка архивов и релизный аудит

Дата: **25.10.2026**. Объект проверки: исходный `AIDoctor-master (12)(1).zip` и итоговая локальная папка `AIDoctor after upgrade.rar` (после этапов 1–5, до этапа 6). Исходный ZIP совпадает по SHA-256 с ранее присланным `AIDoctor-master (12).zip`.

## Решение

**NO-GO для безусловного автоматического деплоя на текущий VDS и тем более для использования с реальными пациентами.** Не выявлено пропущенных файлов этапов 1–5, но критические этапы релизной проверки отсутствуют: Ruff, PostgreSQL-миграция на тестовой копии, полный pytest, живой MCP и браузерный E2E на действующем сервере. Есть особенность workflow: ручные full tests не блокируют push-автодеплой.

Условия GO описаны в новом `README.md`, раздел 15.

## Методика

1. Загруженные ZIP и RAR распакованы изолированно.
2. Сравнение относительных путей и SHA-256 файла; исключены `.git`, `.venv`, `.idea`, `.ruff_cache`, `.pytest_cache`, pycache, данные и локальные `.env`.
3. Отдельно вычислено ожидаемое состояние: исходный ZIP + последовательно TAR.GZ этапов 1–5.
4. Проверены важные конфиги CI, Docker, MCP, новые схемы/сервисы, миграции, маршруты.
5. Проведены локальные статические проверки и ограниченный набор unit/UI/MCP-тестов.
6. Сервер Ubuntu/HTTPS/GitHub Actions реального аккаунта не запускались; PostgreSQL-интеграция не была доступна для тестов.

### Сводка файлов

| Категория | Количество |
|---|---:|
| Файлы исходного ZIP после распаковки | 406 |
| Файлы нового RAR после исключения локальных окружений и служебных папок | 422 |
| Совпадают по SHA-256 | 384 |
| Различаются по SHA-256 | 22 |
| Добавлены в новом RAR | 21 |
| Удалены | 0 |
| Файлы из этапов 1–5, отсутствующие в новом RAR | **0** |

Три изменения не являются новым функциональным кодом: `audit/rollback_report.json` (локальный отчёт), `backend/app/main.py.context-backup` (временная копия), `backend/alembic/versions/aictx_v3_20261017_context_snapshots.py` (только CRLF/LF; нормализованный текст идентичен). Дополнительно присутствуют `.env.test.example`, `docs/site_builder_connection_runbook.md` и локальные `.pytest_cache` тестов.

**Внимание:** оригинальный RAR (до фильтрации) содержит локальные `.env`, `.git`, `.venv`. Не использовать его как развёртываемый или публичный архив. В нём потенциально есть конфиденциальные настройки и история Git. При разглашении за пределы доверенного контура оценить необходимость ротации секретов.

### Файлы, функционально изменённые относительно исходника

- `backend/app/api/routes/ai_review.py`
- `backend/app/api/routes/history_events.py`
- `backend/app/core/access.py`
- `backend/app/db/metadata.py`
- `backend/app/main.py`
- `backend/app/models/__init__.py`
- `backend/app/schemas/ai_review.py`
- `backend/app/services/ai_review.py`
- `backend/app/services/site_doctor_access.py`
- `backend/app/web/assets/app.js`
- `backend/app/web/assets/style.css`
- `backend/app/web/index.html`
- `backend/tests/test_site_multi_doctor_unit.py`
- `backend/tests/test_ui4b_clinical_ui_unit.py`
- `backend/tests/test_ui4b_pg.py`
- `backend/tests/test_ui6b_backend_unit.py`
- `backend/tests/test_ui6b_product_ui_unit.py`
- `deploy/Dockerfile.test`
- `deploy/ci/server_autodeploy.sh`

### Новые файлы без cache/среды

- `.env.test.example`
- `backend/alembic/versions/workspace_s1_20261025_clinical_entry_audit.py`
- `backend/app/api/routes/medical_observations.py`
- `backend/app/models/clinical_entry_audit.py`
- `backend/app/schemas/clinical_entry.py`
- `backend/app/services/clinical_entries.py`
- `backend/demo_cases/aviandr_gad_8weeks_v1.json`
- `backend/scripts/seed_aviandr_case.py`
- `backend/tests/test_ai_analysis_review_stage4.py`
- `backend/tests/test_aviandr_seed_pg.py`
- `backend/tests/test_aviandr_seed_unit.py`
- `backend/tests/test_workspace_s1_pg.py`
- `backend/tests/test_workspace_s1_unit.py`
- `backend/tests/test_workspace_stage2_static.py`
- `backend/tests/test_workspace_stage5_static.py`
- `docs/site_builder_connection_runbook.md`

## Соответствие инкрементам 1–5

Проверка **каждого файла, упакованного на этапах 1–5**, показала отсутствие файловых пропусков. Для всех таких файлов финальные байты совпадают с результатом последовательного наложения архивов. Расхождения нового RAR с ожидаемым набором ограничиваются указанными выше тремя служебными/CRLF случаями и локальными дополнениями. Это доказывает **полноту наложения архивов**, но не корректность приложения в PostgreSQL.


### Этап 1 — клинические API и аудит

- `backend/alembic/versions/workspace_s1_20261025_clinical_entry_audit.py`
- `backend/app/api/routes/history_events.py`
- `backend/app/api/routes/medical_observations.py`
- `backend/app/core/access.py`
- `backend/app/db/metadata.py`
- `backend/app/main.py`
- `backend/app/models/__init__.py`
- `backend/app/models/clinical_entry_audit.py`
- `backend/app/schemas/clinical_entry.py`
- `backend/app/services/ai_review.py`
- `backend/app/services/clinical_entries.py`
- `backend/app/services/site_doctor_access.py`
- `backend/tests/test_site_multi_doctor_unit.py`
- `backend/tests/test_ui4b_pg.py`
- `backend/tests/test_ui6b_backend_unit.py`
- `backend/tests/test_workspace_s1_pg.py`
- `backend/tests/test_workspace_s1_unit.py`
- `deploy/ci/server_autodeploy.sh`


### Этап 2 — единое рабочее место

- `backend/app/web/index.html`
- `backend/app/web/assets/app.js`
- `backend/app/web/assets/style.css`
- `backend/tests/test_workspace_stage2_static.py`


### Этап 3 — импорт клинического кейса

- `backend/demo_cases/aviandr_gad_8weeks_v1.json`
- `backend/scripts/seed_aviandr_case.py`
- `backend/tests/test_aviandr_seed_unit.py`
- `backend/tests/test_aviandr_seed_pg.py`
- `deploy/Dockerfile.test`


### Этап 4 — AI-review из Site Builder

- `backend/app/api/routes/ai_review.py`
- `backend/app/services/ai_review.py`
- `backend/app/schemas/ai_review.py`
- `backend/app/web/index.html`
- `backend/app/web/assets/app.js`
- `backend/tests/test_ai_analysis_review_stage4.py`
- `backend/tests/test_ui4b_clinical_ui_unit.py`
- `backend/tests/test_ui6b_product_ui_unit.py`


### Этап 5 — устойчивость UI

- `backend/app/web/index.html`
- `backend/app/web/assets/app.js`
- `backend/app/web/assets/style.css`
- `backend/tests/test_ui6b_product_ui_unit.py`
- `backend/tests/test_workspace_stage5_static.py`


## Контроль инфраструктуры и MCP

| Объект | Вывод |
|---|---|
| `.github/workflows/ci.yml` | Не изменился. Quick `quality` вызывается на push; PostgreSQL `full_tests` только при `workflow_dispatch`. |
| `deploy/compose.test.yaml` | Не изменился. Запускает `APP_ENV=test`, `aidoctor_synthetic`; `AIDOCTOR_SITE_MULTI_DOCTOR_ENABLED` по умолчанию 0. |
| `deploy/Dockerfile.test` | Изменён: добавлен `COPY backend/demo_cases` для импорта. |
| `deploy/ci/server_autodeploy.sh` | Изменён только инвариант количества синтетических пациентов: ровно 3 → минимум 3. Остальные шаги backup/миграций/rollback сохранены. |
| `backend/app/api/routes/site_doctor_bridge.py` | Не изменился: прежние маршруты MCP v2 остались. |
| `backend/app/api/routes/ai_demo_bridge.py` | Не изменился: старый демо-канал сохранён. |
| `backend/app/services/site_doctor_access.py` | Изменилось правило доступа к несинтетическим пациентам — `external_ai_consent=true`; другие проверки врача и запроса присутствуют. |
| `backend/app/services/ai_review.py` | Существенные изменения: снят synthetic guard, новый импорт AI, врачебное предложение и сохранение различных клинических сущностей. |
| Alembic | Добавлен `workspace_s1_20261025`, единственный head по локальной проверке. |

### Конкретные риски

**R1 — высокий. Автодеплой без обязательного full PG gate.** Workflow `autodeploy` зависит лишь от `quality`; полная проверка PostgreSQL и миграций запланирована только при ручном запуске. Любой push `master` при `VDS_AUTODEPLOY_ENABLED=true` может начать развёртывание после одного быстрого CI.

**R2 — высокий. Изменения схемы PostgreSQL.** Добавляется `clinical_entry_audit`; `alembic heads` успешен, но миграция на тестовой БД и обратная совместимость с прежним образом не подтверждены. Серверный rollback не откатывает миграции.

**R3 — высокий. MCP в настоящем `APP_ENV=production`.** `site_doctor_access.site_enabled()` требует `APP_ENV=test`, поэтому интеграция v2 в настоящем production отключится. Публичный тестовый VDS с `APP_ENV=test` не имеет этой особенности, но не является подтверждённым production-контуром.

**R4 — высокий. Безопасность клиентских и медицинских сценариев.** Широко изменены `app.js`/`index.html`, ручные записи и AI-review. Точечные unit-тесты успешны, живой end-to-end с PostgreSQL/MCP не проведён.

**R5 — средний/высокий. Отсутствие Ruff в проверочной среде.** `ruff check` и `ruff format --check` не были запущены. Изменённые файлы имеют нестандартные форматирование/импорты, поэтому прохождение GitHub `quality` пока не установлено.

**R6 — высокий при публикации архива.** В RAR присутствует `.env` и служебные данные `.git`/`.venv`. Нельзя пересылать/публиковать его как релиз.

**R7 — средний. Несинтетические пациенты.** Ограничение снято в клиническом UI/review; значит, теперь безопасность опирается на серверный доступ и отдельное согласие для Site. Для реальных пациентов требуется формальное тестирование безопасности, разграничения ролей и соответствия требованиям.

**R8 — средний. Импорт кейса.** Скрипт проверен на уровне данных, но не запускался с `--apply`. Пациентка пока не добавлена в БД. Нельзя считать демонстрационный сценарий полного цикла завершённым.

## Проведённые проверки

| Команда / проверка | Факт |
|---|---|
| Python `compileall -q backend/app` | Exit 0 |
| `node --check backend/app/web/assets/app.js` | Exit 0 |
| `python -m alembic -c alembic.ini heads` | Exit 0; `workspace_s1_20261025 (head)` |
| `pytest --noconftest -q` на девяти целевых файлах | 53 passed |
| Расширенный набор без `_pg`, сбор тестов | Не завершён: отсутствует `psycopg` в независимой среде |
| Ruff check + format | Не выполнялся, модуль отсутствует |
| PostgreSQL + миграции | Не выполнялись |
| VDS / HTTPS / MCP живой | Не выполнялись |

**Критерии готовности аудитной задачи:** архивы проинвентаризированы, этапы наложены полностью, новые маршруты/MCP/CI/миграции локализованы, основные риски описаны. **Граница:** это статический и ограниченный тестовый аудит, а не production acceptance test.

## Протокол выпуска, безопасный минимум

1. Скопировать актуальный README в локальный проект, оставить `.env` вне Git.
2. Установить зависимости из `requirements-dev.txt`.
3. Запустить `ruff check backend`, `ruff format --check backend`, Python compilation и Node check.
4. Убедиться, что `alembic heads` имеет ровно одну вершину.
5. Проверить восстановимость backup на отдельной тестовой БД, выполнить миграцию и полный pytest.
6. В GitHub запустить ручной `workflow_dispatch` и проверить job `full_tests`.
7. На тестовом стенде проверить реальный MCP, права двух врачей, смену пациента, approve/reject, rollback сценарий.
8. Проверить, что server checkout чист, volume существует и секреты имеют верные права.
9. Только после прохождения всего списка разрешить push в `master`.
10. После миграции и smoke-test отдельно применить отложенный `seed_aviandr_case --apply` в `aidoctor_synthetic`, с идемпотентным повторным запуском.

**Не выполнять без отдельного плана:** `docker compose down -v`, `alembic downgrade`, `pg_restore` в существующую базу, удаление пациентов, смену `APP_ENV` на production ради обхода Site guard.

## Конфликтный анализ

1. **Владение данными:** AI и приложение не должны конкурировать за запись «истины»; physician review остаётся обязательным.
2. **Контракты:** v2 MCP маршруты неизменны, но политики доступа пересмотрены; нужны матричные проверки двух врачей и согласия.
3. **Эволюция:** добавление пациентов больше не ломает инвариант `=3`; конкуренция AI-review и миграции требуют проверки на общей PostgreSQL.

## Границы ответственности

Этот отчёт не удостоверяет работу действующего VDS, полноту требований регуляторов или безопасность для реальных пациентских данных. Команды развёртывания, проверки и отката приведены **в README и должны дополнительно объясняться непосредственно в чате**.
