# AIDoctor Clinical Response v1 — интеграционный пакет (демо)

Это **проектный контракт**, подготовленный по синтетическому 8-недельному случаю ГТР/Авиандр. **Новые endpoints, автозапись и автоматическая доставка алертов этим пакетом не внедрены.** Он добавляет схему и 24 тестовых JSON-файла; существующее приложение не переписывается.

## Что добавлено
- `docs/clinical_response_v1/clinical_response.v1.schema.json` — строгий JSON Schema Draft 2020-12.
- `docs/clinical_response_v1/examples/*.json` — 24 синтетических ответа: 8 штатных точек и 16 альтернативных веток.
- `docs/clinical_response_v1/README.md` — сопоставление с существующей архитектурой, внедрение, откат.
- `docs/clinical_response_v1/validate_examples.py` — офлайн-проверка fixtures; для полноценной схемной проверки нужен `jsonschema`.

## ВАЖНО: текущая архитектура
В репозитории уже есть `aidoctor_demo_analysis.v1` (Pydantic: `backend/app/schemas/ai_demo_bridge.py`) и `aidoctor_structured_proposals.v1` (`backend/app/schemas/ai_structured_proposals.py`), а также `AIReview` и ручные клинические API.
Новый `aidoctor_clinical_response.v1` **не принимается существующим маршрутом** `POST /api/v1/integrations/site-builder/demo-analyses`: там `extra=forbid`, другие обязательные поля, проверка заранее сохранённого `AIRequest`, UUID и реальных хешей.
Его нельзя отправлять в указанный endpoint «как есть».

### План интеграции
1. Добавить адаптер `clinical_response -> DemoAnalysisSubmit` **без потери ограничений существующего метода**: summary, hypotheses, medication_risks, missing_information, suggested_examinations, sources; проверить `request_id`, `patient_id`, `context_sha256` и `orders_sha256`, полученные из серверного контекста, а не из fixture.
2. Для действий с историей болезни/наблюдениями/назначениями формировать **предложения** `ai_review.Proposal` с `evidence_status=unverified_ai`, используя существующие `ManualHistoryCreate`, `ManualObservationCreate`, `OrderDraftCreate`; нельзя напрямую писать в clinical tables.
3. Врачу показывать preview/diff, отдельно подтверждать `ReviewCommit` с актуальной `expected_version` и `preview_sha256`; выполнять через серверные права и аудит.
4. Поля `alerts` — **только кандидат на событие**. Диспетчер безопасности самостоятельно перепроверяет входные сигналы и создаёт алерт в собственном контуре с доставкой, retries и подтверждением. `dispatch=proposed_not_sent` не означает, что алерт доставлен. Срочные инструкции пациенту показывать независимо от доставки.
5. `referrals` — предложения врачу, а не автоматически выписанные направления; перед публикацией проверять условия закона РФ и медицинские основания.
6. Проверять российскую инструкцию в ГРЛС, противопоказания, почки, печень, беременность, сочетания. Дозы из синтетического случая **не являются подтверждением актуальной регистрации**.
7. Не использовать `.json` fixture как реальную медицинскую запись, не передавать PHI в демо-данные. Нельзя полагаться на условные проценты диагностической уверенности как на калиброванные вероятности.

## Распределение по категориям

| Поле | Назначение | Автозапись |
|---|---|---|
| `history_draft` | Черновик истории болезни/визита | Только staging / pending-review |
| `observations` | Черновики шкал и показателей | Только staging / без подтверждения |
| `medication_proposals` | Черновики предложений по лечению | Нет назначения без врача |
| `alerts` | Вход для независимой системы оценки риска | Только после серверного rule-engine |
| `referrals` | Маршрутизация на рассмотрение | Только решение врача |
| `display` | Текст для двух ролей | С учётом прав и safety filtering |
| `provenance` | Привязка и проверка неизменности | Серверная верификация |

## Коммиты демоверсии и откат

**ФАКТ:** исходный `AIDoctor-master (17).zip` не содержит `.git/`. Поэтому фактические SHA, авторов, даты и границы существующих demo-коммитов определить по нему **невозможно**. Внутренние даты в именах миграций (`ai_bridge_v1_20261024...`, `workspace_s1_20261025...`) не являются коммитами. Ниже — **предлагаемые новые коммиты**, не ранее сделанные и не выдуманные SHA:

| Порядок | Рекомендуемое сообщение нового коммита | Изменения |
|---|---|---|
| 1 | `demo(contract): add clinical response v1 schema` | `docs/clinical_response_v1/clinical_response.v1.schema.json` |
| 2 | `demo(fixtures): add 24 synthetic clinical response scenarios` | `docs/clinical_response_v1/examples/` |
| 3 | `demo(validation): add offline clinical response tests` | `docs/clinical_response_v1/validate_examples.py` |
| 4 | `docs(demo): document response integration and rollback` | `docs/clinical_response_v1/README.md`, раздел главного `README.md` |

**Чтобы зафиксировать действительные SHA после локальных коммитов** (на рабочей копии репозитория, не на живом сервере):
```bash
git status --short
git log --oneline --decorate -30
git log --oneline --all --grep='demo(contract)\|demo(fixtures)\|demo(validation)\|docs(demo)' --extended-regexp
git log --format='%H %s' -- docs/clinical_response_v1/
```
Перенесите реальные SHA в это README после создания коммитов; не подставляйте примерные значения.

**Изолированный откат только файлов данного пакета**, если для него действительно созданы 4 отдельных коммита и они не содержат чужих изменений:
```bash
git switch -c rollback-clinical-response
git revert <SHA_4> <SHA_3> <SHA_2> <SHA_1>
```
Здесь SHA_4 — наиболее новый коммит, SHA_1 — самый ранний. `git revert` предпочтительнее `reset` на опубликованной ветке. Для незафиксированных в Git новых файлов — отдельно проверить `git status`, затем убрать только `docs/clinical_response_v1/` и соответствующий блок главного README. НЕ запускать `git reset --hard`, `git clean -fd`, не удалять миграции и таблицы PostgreSQL без отдельного плана.

**Для исторических демо-доработок проекта**, уже присутствовавших в ZIP, точно установить границы возможно только в репозитории с `.git`; использовать `git log --name-status -- backend/app/api/routes/ai_demo_bridge.py backend/app/schemas/ai_demo_bridge.py backend/demo_cases/aviandr_gad_8weeks_v1.json` и сверить с `AIDoctor_RELEASE_AUDIT_2026-10-25.md`. Не откатывать эти изменения по списку файлов вслепую: они могут содержать совместные правки и миграции.

## Проверки и ограничения
```bash
python docs/clinical_response_v1/validate_examples.py
```
Для проверки всех ограничений JSON Schema нужен пакет `jsonschema`. Валидатор не поднимает сервер, не соединяется с БД и не меняет назначения. Полную регрессию и миграции проверять отдельно только на выделенной тестовой БД. Текущий release audit проекта имеет статус **NO-GO** до дополнительных проверок.

Источники синтетического случая: загруженный документ «Клинический кейс Авиандр 8 недель» и задание чемпионата. Ветви вне основной траектории специально вымышлены; доказательность терапии и актуальность ГРЛС должны быть проверены перед реальным применением.
