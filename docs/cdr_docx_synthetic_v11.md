# AIDoctor — этап 6.4.2b: изолированный DOCX→PDF→JPEG→PDF

## Назначение и границы

Добавлена **отдельная демонстрационная сборка Docker для синтетического DOCX**,
которая действительно вызывает LibreOffice Writer в режиме без интерфейса,
передаёт промежуточный PDF в прежний Poppler/`img2pdf` worker и возвращает
новый PDF. Это техническая проверка исполнимого конвейера, **не аттестованный
CDR для документов пациентов**. Никакие клинические маршруты, статусы,
вложения PostgreSQL, оригиналы файлов и Context Builder не затрагиваются.
Результат — `UntrustedCDROutput`; `trusted=False`, `sanitized=False`,
`processing_allowed=False`.

**Синтетический источник** фиксирован в коде, генерируется в памяти и содержит
только строку `AIDoctor synthetic DOCX test only`. CLI не поддерживает
пути к файлам, произвольные байты, идентификаторы пациента и API ключи.

Для опытного DOCX-worker на уровне контейнера разрешён только минимальный
пакет OOXML из трёх XML-частей; блокируются посторонние ZIP-части,
внешние связи, макросы, встраиваемые объекты, DDE-поля, подозрительное XML,
чрезмерная степень сжатия и изменение синтетического текста. Это
**не полноценная валидация DOCX**, не антивирус и не подтверждение
защиты LibreOffice от уязвимостей. Реальные DOCX пока **не поддерживаются**.

## Установочные зависимости

`Dockerfile.docx` собирается *отдельно* от старого `Dockerfile` (PDF),
используя `python:3.12-slim-trixie` и пакеты Debian `libreoffice-writer`,
`poppler-utils`, `img2pdf`, `fonts-dejavu-core`. Они скачиваются только при
явном запуске команды `docker build` и устанавливаются только **в Docker**,
не в `.venv`. Образ может быть большим (сотни МБ и более).
Контекст сборки строго `backend/cdr_image`, ограниченный `.dockerignore`;
не используйте `docker build .` из корня проекта.

Base image не закреплён digest; пакеты могут изменяться, у LibreOffice
публикуются исправления уязвимостей. До любых реальных данных необходимы
review поставки, SBOM, digest-пиннинг и более строгая изоляция.

## Команды Windows / PowerShell

Из корня проекта, после замены файлов из ZIP:

```powershell
python -m ruff check backend
python -m pytest backend/tests/test_cdr_docx_worker_unit.py -v -rs
python -m pytest backend/tests/test_cdr_docx_synthetic_execution_unit.py -v -rs

python -m alembic -c alembic.ini current -v
python -m alembic -c alembic.ini check

# Опционально: реальная сборка, скачивание большого образа и Debian-пакетов.
docker build -f backend/cdr_image/Dockerfile.docx -t aidoctor-cdr:docx-synthetic backend/cdr_image

# Локальный полный image ID, не tag:
$imageId = docker image inspect aidoctor-cdr:docx-synthetic --format '{{.Id}}'

# Только фиксированный синтетический DOCX:
$env:PYTHONPATH = (Resolve-Path .\backend).Path
python -m app.workers.cdr_docx_synthetic_once --run-synthetic --image-id $imageId
Remove-Item Env:PYTHONPATH
```

Ожидаемый результат: строка `PASS: синтетический DOCX преобразован ...`,
SHA-256 нового PDF и явный запрет медицинской обработки.

Проверка всей регрессии только с выделенной тестовой БД:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
python -m pytest backend/tests -v -rs
Remove-Item Env:TEST_DATABASE_URL
```

⚠️ PostgreSQL-фикстуры могут удалять и создавать таблицы; никогда не
использовать БД с реальными пациентами.

## Контракт исполнения и конкуренция

- Вход/выход — ограниченные двоичные stdin/stdout, без mount, Docker API
  из контейнера, сетевых портов или сокета Docker.
- Docker `--network=none`, `--ipc=none`, `--read-only`,
  `--cap-drop=ALL`, `--security-opt=no-new-privileges`,
  UID:GID 65534, `--pids-limit=64`, CPU 1, RAM 2 ГиБ,
  изолированный tmpfs 256 MiB (`noexec,nosuid,nodev`), `--ulimit` для FD.
- Docker выбирается по **точному локальному `sha256:` image ID**, имя
  контейнера создаётся случайным, после исполнения выполняется
  `docker rm --force`. Эти меры не удостоверяют Docker daemon,
  его контекст или происхождение образа.
- Конвертер работает с уникальной временной директорией, профилем
  LibreOffice внутри неё, обрабатывает не более восьми страниц.
  Промежуточный PDF не выносится наружу; итог получается из JPEG.
- Подпроцессы и общий Docker запуск имеют таймауты, stderr/PHI не
  выводятся; при сбое не выдаётся «чистый» результат.
- Повторный AV выходного PDF, аудит результата клинических документов,
  проверка достоверности конвертера и release из карантина отсутствуют.

## Три вида архитектурных конфликтов

1. **Данные/инварианты.** PostgreSQL остаётся источником статусов/аудита;
   оригиналы — в отдельном карантинном storage. Синтетический процесс
   ничего не записывает в БД и не меняет статус вложений.
2. **Контракты.** Существующий путь PDF, HTTP API, Alembic, AV и
   `require_processing_clearance` не изменены. Для DOCX отдельный
   Dockerfile и сервис с прежним `UntrustedCDROutput` на выходе.
3. **Эволюция.** Реальный клинический CDR должен получить независимый
   авторизованный и аудитируемый сервис, выделенную sandbox-среду,
   подтверждение надёжности AV/CDR, перезапуск AV на выходе, проверку
   эквивалентности содержания и правила доверия/клинического допуска.

## Критерии готовности

1. Ruff и новые unit-тесты без ошибок.
2. Полный Windows/PostgreSQL pytest и `alembic check` зелёные.
3. Docker-образ DOCX успешно собирается и smoke-test возвращает `PASS`.
4. PDF-only smoke-test этапа 6.4.2a остаётся работоспособным при необходимости
   без пересборки своего Dockerfile.
5. Ни один клинический файл не передаётся в контейнер; Context Builder закрыт.

## Риски / границы

Преобразование в JPEG уничтожает машинно читаемый текст. Без OCR текст
не станет доступным Context Builder (OCR и LLM **не включены**).
LibreOffice — значимая поверхность атак; Docker Desktop не является
гарантированно изолированной песочницей уровня VM/gVisor. DOCX нельзя
считать безопасным по одному успеху преобразования. На выходе остаётся
**недоверенный PDF**. Реальный контейнер должен быть проверен в Windows;
если сборка или smoke-test не прошли — этап не подтверждён.

**Следующий этап:** 6.5 — проектирование аудита и повторной AV-проверки
недоверенного результата, затем 6.6 — финальная security-регрессия.
Для клинического допуска потребуется отдельное решение и проверка рисков,
не только формальное завершение номера этапа.
