# CI: быстрые проверки на push, полные тесты вручную

**Режим:** временно до устранения пяти выявленных падений pytest.
GitHub Actions не выполняет модульные и PostgreSQL-тесты автоматически на `push`
и `pull_request`. Они сохраняются и запускаются вручную на событии
`workflow_dispatch`. Это **не означает**, что все тесты проходят.

## Автоматически на push/PR

- Ruff lint и format;
- синтаксис JavaScript;
- компиляция Python;
- без PostgreSQL, Alembic и pytest;
- production-деплой не выполняется.

## Вручную перед развёртыванием

GitHub → Actions → «Проверка AIDoctor» → Run workflow.
Выполняются обе задачи: быстрые проверки и отдельная полная
проверка с PostgreSQL 16, миграциями и `pytest backend/tests`.

Полный прогон также требуется перед добавлением реальных пациентов
или изменениями клинических контрактов. Ошибки нельзя трактовать
как несущественные до анализа `FAILURES`.

## Локально на Windows / PowerShell

```powershell
python -m ruff check backend
python -m ruff format --check backend
node --check backend/app/web/assets/app.js
python -m compileall -q backend/app
python -m pytest backend/tests/test_ci_workflow_unit.py -q
```

Для полной проверки подготовьте **только тестовую** PostgreSQL-БД,
имя которой заканчивается на `_test`:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m pytest backend/tests -q --tb=short
Remove-Item Env:TEST_DATABASE_URL -ErrorAction SilentlyContinue
```

Проверяйте, что `TEST_DATABASE_URL` указывает на выделенную локальную БД.
`pg_engine` удаляет и создаёт таблицы в этой БД.

## Linux (локальная тестовая среда)

```bash
python -m ruff check backend
python -m ruff format --check backend
node --check backend/app/web/assets/app.js
python -m compileall -q backend/app
python -m pytest backend/tests/test_ci_workflow_unit.py -q
```

Для полного прогона:
```bash
export TEST_DATABASE_URL="postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m pytest backend/tests -q --tb=short
unset TEST_DATABASE_URL
```

Не запускайте pytest по production-БД и не используйте туда синтетические
сценарии автоматически.

## Готовность и риски

1. В YAML `quality` не имеет сервиса PostgreSQL и не запускает pytest.
2. На `push` и `pull_request` выполняются только статические проверки.
3. При `workflow_dispatch` выполняются миграции и все тесты на выделенной
   тестовой PostgreSQL-БД.
4. Зафиксированы исходные 5 падений, а не замаскированы как исправленные.
5. К публикации допускаем только после успешного ручного прогона.

Не изменены клинические API, миграции, таблицы, файлы пациентов и логика
утверждения назначений. Режим CI требует пересмотра после исправления тестов.
