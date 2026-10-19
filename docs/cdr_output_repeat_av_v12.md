# AIDoctor — 6.5.0: повторное AV-сканирование синтетического CDR-выхода

## Назначение

Инкремент соединяет существующие механизмы 6.3.3 и 6.4.2:
встроенный синтетический PDF/DOCX → изолированная растеризация Docker →
`UntrustedCDROutput` → **повторная** проверка ClamAV с EICAR-гейтом.

**Этот этап не обрабатывает файлы пациентов и не является допуском к
Context Builder.** Не открывает HTTP API, не вызывает OCR/LLM,
не пишет в PostgreSQL и не снимает карантин.

## Границы и контракт

- Внешний вход возможен только из `SyntheticCDRResult` или
  `SyntheticDOCXResult` предыдущих этапов.
- SHA-256 исходника должен соответствовать именно встроенному
  синтетическому примеру (`synthetic_pdf()` или `synthetic_docx()`).
  Произвольные пользовательские байты не должны попадать в этот контур.
- Проверяются тип данных, длина (до 20 МиБ), SHA-256 результата,
  формат PDF, маркер окончания и несовпадение с исходником.
- Сканирование выполняется через `PreflightGatedScanner`: EICAR и свежесть
  базы до передачи PDF, при `clean_reported` — EICAR и сверка версии
  после ответа. Прямой `ClamdScanner` отклоняется на границе сервиса.
- Повторная проверка объекта после AV предотвращает возврат `clean_reported`,
  если метаданные изменились во время операции.
- `clean_reported`/`infected_reported`/`error` — **сообщения локального
  сканера**, не медицинский или клинический вердикт.
- Квитанция не содержит байтов, путей, пациента, его имени или текста.
  Любая квитанция: `trusted=False`, `sanitized=False`,
  `processing_allowed=False`.
- TCP clamd не имеет встроенной аутентификации; EICAR не удостоверяет
  подлинность демона и не заменяет проверку происхождения образа/баз.

## Файлы

- `backend/app/services/cdr_synthetic_output_av.py` — только политика
  и временная квитанция.
- `backend/app/workers/cdr_synthetic_av_once.py` — выключенная по умолчанию
  ручная операция с одним встроенным синтетическим примером.
- `backend/tests/test_cdr_synthetic_output_av_unit.py` — позитивные
  и негативные сценарии.

Миграция не нужна. Долговременный PostgreSQL-аудит **не реализован**,
поскольку реальный пациентский CDR-выход пока не разрешён. Вывод CLI —
диагностическая квитанция, а не надёжный неизменяемый журнал.

## PowerShell (Windows 11, из корня репозитория)

Проверить существующий ClamAV (ожидается `healthy`):

```powershell
docker compose -f compose.yaml -f compose.av.yaml --profile av ps
python -m ruff check backend
python -m pytest backend/tests/test_cdr_synthetic_output_av_unit.py -v -rs
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini check
```

Дополнительные тесты для протокола и предыдущего CDR:

```powershell
python -m pytest backend/tests/test_attachment_av_policy_unit.py -v -rs
python -m pytest backend/tests/test_cdr_synthetic_execution_unit.py -v -rs
python -m pytest backend/tests/test_cdr_docx_synthetic_execution_unit.py -v -rs
```

Если готов локальный PDF CDR-образ с прошлого этапа, можно выполнить
**настоящую** синтетическую конвертацию и повторный AV:

```powershell
$pdfImageId = docker image inspect aidoctor-cdr:synthetic --format '{{.Id}}'
$env:PYTHONPATH = (Resolve-Path .\backend).Path
$env:ATTACHMENT_CLAMD_ENABLED = "true"
python -m app.workers.cdr_synthetic_av_once --once --pdf-image-id $pdfImageId
Remove-Item Env:ATTACHMENT_CLAMD_ENABLED
Remove-Item Env:PYTHONPATH
```

Для синтетического DOCX — отдельный образ, собранный на этапе 6.4.2b:

```powershell
$docxImageId = docker image inspect aidoctor-cdr:docx-synthetic --format '{{.Id}}'
$env:PYTHONPATH = (Resolve-Path .\backend).Path
$env:ATTACHMENT_CLAMD_ENABLED = "true"
python -m app.workers.cdr_synthetic_av_once --once --docx-image-id $docxImageId
Remove-Item Env:ATTACHMENT_CLAMD_ENABLED
Remove-Item Env:PYTHONPATH
```

Команды не получают пути или ID пациентских вложений. Если статус не
`clean_reported`, CLI возвращает ненулевой код, а в любом случае
**не освобождает файл из карантина**.

Полная регрессия только в выделенной локальной `_test` БД:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m pytest backend/tests -v -rs
Remove-Item Env:TEST_DATABASE_URL
```

**Осторожно:** PostgreSQL фикстура может удалять и пересоздавать
таблицы указанной БД.

## Критерии готовности

1. Ruff без ошибок, новый unit-тест прошёл.
2. Полный pytest и Alembic Check без ошибок.
3. Реальный PDF CDR → AV smoke-test возвращает `clean_reported`
   при работающем `clamd` и свежих сигнатурах.
4. Опциональный DOCX smoke-test прошёл.
5. Все квитанции сохраняют `processing_allowed=False`.
6. Недоступность сканера, EICAR-сбой, нарушение SHA или изменение
   версии не могут породить `clean_reported`.

## Архитектурные конфликты

- **Владение данными:** PostgreSQL и хранилище оригиналов не меняются.
  Квитанция временная и не является источником статуса пациента.
- **Контракты:** сохранены старые API, Alembic и существующий
  `require_processing_clearance`.
- **Расширяемость:** реальное разрешение использовать санитаризированный
  медицинский файл требует отдельного аудируемого жизненного цикла
  (ID исходника → pinned CDR image → output hash → повторный AV →
  ручное заключение), безопасного хранения выхода и проверок доступа.

## Следующее

6.5.1 — PostgreSQL-аудит результата для **специально разрешённого**
реального пайплайна и независимая политика допуска. До реализации и
согласования этого контура клиническая обработка запрещена.

6.6 — регрессионные security-тесты и эксплуатационная стабилизация.
