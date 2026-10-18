# Этап 6.1 — ручные непроверенные выдержки с происхождением

## Зачем

Текущие PDF, DOC/DOCX, изображения и аудиозаписи загружаются со статусом
`quarantined`. Антивирусного сканирования, CDR, OCR, STT, безопасной
изоляции парсеров и LLM **нет**. Поэтому 6.1 НЕ открывает байты вложений
и НЕ меняет `extraction_status`.

На этом шаге врач может вручную записать **непроверенную выдержку**,
ссылаясь на метаданные загруженного вложения. Такая выдержка не считается
фактом или результатом автоматического извлечения, не участвует в
Context Builder / Digest / Delta, не порождает наблюдения или диагнозы.

## API (относительно `/api/v1`)

| Метод | Путь | Действие |
| --- | --- | --- |
| `POST` | `/patients/{patient_id}/attachments/{attachment_id}/evidence-drafts` | Создать выдержку, `201` |
| `GET` | тот же | Прочитать не более 50 последних выдержек |

POST тело (использовать **только синтетические** данные):

```json
{
  "source_locator": "стр. 2, абзац 3",
  "excerpt": "Синтетическая выдержка для теста."
}
```

Ограничения: до 120 символов локатора, до 2000 символов выдержки.
Разрешены переносы строк в выдержке; запрещены недопустимые управляющие
символы. Пробелы по краям удаляются, Unicode нормализуется в NFC;
внутренние пробелы и переносы строк сохраняются.

Ответ содержит `id`, `patient_id`, `attachment_id`, `created_by_id`,
`created_at`, `source_locator`, `excerpt`, исходный
`attachment_sha256`, собственный `excerpt_sha256` и фиксированные
`source_kind=manual`, `verification_status=unverified`.
`attachment_sha256` скопирован из PostgreSQL **на момент записи**,
не является повторной проверкой физического файла.

Одинаковые `(attachment_id, created_by_id, source_locator, excerpt_sha256)`
возвращают прежнюю запись (`201`) через `ON CONFLICT DO NOTHING`.
Это идемпотентность черновика, не защита от семантически похожих формулировок.
Нет UPDATE/DELETE или подтверждения данных.

Читать и создавать может только врач с действующей связью с пациентом.
Для другой роли `403`, для чужого врача или несовпадения пациента
и вложения — `404`. Проверяемые строки пациента, связи и вложения
защищены `FOR SHARE` до фиксации транзакции, чтобы отзыв прав не обгонял
успешное чтение или запись. Для удалённого пациента также `404`. Успешные
GET, включая пустые списки, атомарно записывают
`attachment_evidence_read_audit`, не сохраняя текст ответа.
При ошибке записи аудита данные не возвращаются. Кэширование запрещено
`Cache-Control: private, no-store`.

## PostgreSQL и ответственность

- `medical_attachments` остаётся источником истины о вложении;
- `attachment_evidence_drafts` — неизменяемые, непроверенные записи с SHA;
- `attachment_evidence_read_audit` — метаданные успешных чтений;
- исходные байты файла никогда не обрабатываются этим API;
- потенциальные медицинские тексты в drafts требуют отдельного шифрования,
  retention, экспортного контроля и расширенного аудита перед production.

Миграция `aiextract_v1_20261018`, родитель `aisafe_v7_20261018`.
Удаляющий downgrade запрещён. Новых библиотек и фоновых процессов нет.

## Проверка Windows / PowerShell

```powershell
docker compose up -d postgres
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini heads
# до миграции: current = aisafe_v7_20261018, heads = aiextract_v1_20261018
python -m alembic -c alembic.ini upgrade head
python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini check
python -m ruff check backend
python -m pytest backend/tests/test_attachment_evidence_unit.py -v
. .\scripts\postgres_test_db.ps1
python -m pytest backend/tests/test_attachment_evidence_pg.py -v -rs
python -m pytest backend/tests -v -rs
```

`test_attachment_evidence_pg.py` не должен иметь `SKIPPED`.
Тестовая фикстура удаляет схему **только** в локальной БД `_test`.
Проверить путь `TEST_DATABASE_URL` перед запуском.

## Следующее техническое продолжение

6.2: отдельный безопасный scanner/CDR gate для допустимых форматов и
однозначный статус проверки. 6.3: извлечение из разрешённых форматов в
изолированной среде с лимитами времени и размера. 6.4: врачебная
верификация выдержек перед добавлением в Clinical Context.
Сервис 6.1 **не** запускает эти процессы.
