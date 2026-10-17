# Медицинские вложения: локальный MVP

## Контракты

- `POST /api/v1/patients/{patient_id}/attachments` — `multipart/form-data`, поле `file`.
- `GET /api/v1/patients/{patient_id}/attachments` — последние 100 записей.
- `GET /api/v1/patients/{patient_id}/attachments/{attachment_id}` — скачивание.
- Доступ по действующему bearer-токену; права проверяются через `require_patient`.
- При загрузке возвращается `extraction_status: quarantined`: антивирусная проверка
  и извлечение данных **не реализованы**. LLM не должен использовать такие файлы.

Форматы: PDF, DOC, DOCX, JPG/JPEG, PNG, WEBP, TIFF, WAV, MP3, OGG, FLAC, M4A.
Максимум 20 МиБ на файл. Проверяются расширение и сигнатура; это **не**
полная проверка безопасности документа. Файлы никогда не обслуживаются как статика.

## Данные и транзакции

PostgreSQL хранит `medical_attachments` (владелец, хэш SHA-256, размер,
служебный ключ). Оригинал находится в `ATTACHMENTS_DIR` под непрозрачным UUID-ключом.
При ошибке БД созданный файл удаляется. Миграции не требуются.

Локальная директория по умолчанию `data/attachments/` исключена из Git.
В production обязательны отдельные защищённые хранилище и резервное копирование;
при нескольких инстансах backend локальный диск нужно заменить на общий backend
хранения без изменения публичного API.

## Проверка на Windows / PyCharm

В корне проекта PowerShell:

```powershell
python -m pip install -r requirements-dev.txt
docker compose up -d postgres
.\scripts\postgres_test_db.ps1
python -m ruff check backend
python -m pytest backend\tests\test_attachment_storage.py -v
python -m pytest backend\tests\test_attachment_api.py -v -rs
python -m alembic -c alembic.ini current
python -m alembic -c alembic.ini check
```

Тесты API работают только с `TEST_DATABASE_URL`, указывающим на локальную
PostgreSQL-БД с суффиксом `_test`. `SKIPPED` — не подтверждение результата.

В Swagger после `POST /api/v1/auth/login` нажать **Authorize**,
выбрать связанного с пациентом врача, загрузить синтетический `study.pdf`,
проверить список и скачать файл.

## Ограничения безопасности

Это MVP для синтетических данных, **не** для реальных пациентов:
- нет антивирусного сканирования, CDR и песочницы для DOC/PDF;
- нет шифрования файлов на уровне приложения или управления ключами;
- нет лимита всего HTTP multipart-запроса до его парсинга FastAPI:
  на reverse proxy нужен лимит тела запроса;
- нет общей object storage, фонового сканера, политики удаления/retention,
  журнала доступа к файлам и поддержки восстановления после аварий;
- для Windows необходимо ограничить ACL каталога с вложениями;
- нельзя публиковать каталог как static или передавать его ключи клиенту/LLM.

Перед интернет-релизом необходимы отдельные меры ИБ и проверка правовых требований.
