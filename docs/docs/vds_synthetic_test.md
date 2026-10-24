# DEPLOY-2 TEST — AIDoctor с синтетическими пациентами

Целевая ВМ: FirstVDS #18647543, Ubuntu 24.04.5 LTS, IP 185.200.179.238.
Docker 29.9.2 и Compose v5.6.1 уже установлены и проверены (`hello-world`).
**Не устанавливайте Docker повторно.**

## Архитектура

- `postgres:16`, БД `aidoctor_synthetic`, сохранение в `pg_synthetic`;
- `aidoctor_test` создаётся отдельно только для последующих разрушающих pytest;
- `app`: оригинальный FastAPI и исходные миграции Alembic;
- `seed`: временный контейнер для 3 синтетических пациентов С-001/2/3,
  аккаунтов `doctor_ui1`, `patient_ui1`, `admin_ui1`, Safety Alert и учебных
  лекарственных **черновиков** (не активных назначений);
- браузер получает доступ только по SSH-туннелю. `5432` не опубликован,
  приложение слушает **только 127.0.0.1:18080** на VDS.

Никакой копии локальной Windows PostgreSQL. Используется **точный архив
`AIDoctor-master (8).zip`**, переданный владельцем. Текущая публичная ветка
GitHub может не совпадать с архивом и автоматически не клонируется.

## 1. Загрузить два ZIP с Windows на VDS

Скачайте исходный архив проекта и ZIP этого этапа. Названия файлов в примере
соответствуют именам скачивания. В Windows PowerShell:

```powershell
scp "$env:USERPROFILE\Downloads\AIDoctor_SOURCE_2026-10-24.zip" root@185.200.179.238:/root/AIDoctor-source.zip
scp "$env:USERPROFILE\Downloads\AIDoctor_DEPLOY_2_TEST_2026-10-24.zip" root@185.200.179.238:/root/
```

Если файлы сохранились в другое место, замените пути на фактические.
Не отправляйте на сервер папку Windows с `.env`, `data/attachments` или локальной БД.

## 2. Установить тестовое приложение (терминал Ubuntu)

Следующий блок предполагает *первый запуск*, как в сообщении владельца
(`Каталог приложения: /opt/aidoctor`, сайт и БД ещё не запускались).
**Не продолжайте, если /opt/aidoctor/AIDoctor уже существует.**

```bash
test -f /root/AIDoctor-source.zip && test -f /root/AIDoctor_DEPLOY_2_TEST_2026-10-24.zip || {
  echo "Не найдены оба ZIP в /root"; false;
}
test ! -e /opt/aidoctor/AIDoctor && test ! -e /opt/aidoctor/AIDoctor-master || {
  echo "Обнаружено ранее развёрнутое приложение: остановите команду и изучите каталог"; false;
}
unzip -q /root/AIDoctor-source.zip -d /opt/aidoctor
mv /opt/aidoctor/AIDoctor-master /opt/aidoctor/AIDoctor
cd /opt/aidoctor/AIDoctor
unzip -oq /root/AIDoctor_DEPLOY_2_TEST_2026-10-24.zip
bash deploy/01_start_test.sh
bash deploy/02_check_test.sh
```

Не запускать тесты на `aidoctor_synthetic` с пересозданием таблиц.
Не вводить `docker compose down -v` — это удаляет том с тестовой БД.

## 3. Открыть кабинет в браузере Windows

В **новом Windows PowerShell** (не на Ubuntu):

```powershell
ssh -N -L 18080:127.0.0.1:18080 root@185.200.179.238
```

Пока окно туннеля открыто, браузер Windows:
`http://127.0.0.1:18080/app`.

Учётные записи:
- Врач: `doctor_ui1`
- Пациент: `patient_ui1`
- Администратор: `admin_ui1`

Пароли автоматически созданы на VDS в `.env.test`.
Узнать их **только в приватном терминале Ubuntu** (не пересылать в чат):

```bash
cd /opt/aidoctor/AIDoctor
grep '^DEMO_.*_PASSWORD=' .env.test
```

Публичный адрес `http://185.200.179.238:18080/app` **недоступен намеренно**.

## 4. Диагностика

```bash
cd /opt/aidoctor/AIDoctor
bash deploy/02_check_test.sh
docker compose --env-file .env.test -f deploy/compose.test.yaml ps
docker compose --env-file .env.test -f deploy/compose.test.yaml logs --tail=80 app
```

Если приложение не healthy — не удалять тома, сохранить первые сообщения ошибки
(исключив токены и клинические сведения).

Остановить *без удаления данных*:

```bash
docker compose --env-file .env.test -f deploy/compose.test.yaml down
```

Поднять повторно:

```bash
docker compose --env-file .env.test -f deploy/compose.test.yaml up -d --wait postgres app
```

## 5. Проверка и границы безопасности

- База имеет уникальное имя и Docker volume; локальная Windows БД не затронута.
- Seed проверяет фактическое имя PostgreSQL и `APP_ENV=test`, запрещает данные
  без `synthetic=true` и сохраняет ранее созданные учётные записи.
- Никаких публичных портов FastAPI/PostgreSQL; только SSH-туннель.
- Установка HTTPS, proxy, мониторинга и backup/restore — отдельный этап.
- На UFW ранее обнаружены многочисленные ALLOW-порты (FTP, SMTP, DNS,
  ispmanager). До публичного запуска нужно проверить список слушающих служб и
  закрыть ненужные правила без потери SSH. Комплект их не изменяет.
- Не использовать настоящие медицинские данные; 5 ранее упавших pytest-тестов
  требуют диагностики до production.

## Три класса конфликтов

1. **Владение данными**: PostgreSQL в `pg_synthetic` — единственный источник
   тестовых фактов, врач утверждает назначения; старые скрипты не используются для записи на VDS.
2. **Контракты**: действующие API и Alembic неизменны; инфраструктура
   добавляется отдельными новыми файлами.
3. **Эволюция**: защищённый HTTPS, новый AI-провайдер и реальные БД
   будут добавляться отдельно, не меняя интерфейсы трёх кабинетов.

## Критерии готовности

1. `docker compose config --quiet` завершается без ошибок.
2. `app` и `postgres` имеют состояние healthy.
3. `/api/v1/health` возвращает `environment=test`, `/app` — HTTP 200.
4. В `aidoctor_synthetic` ровно три `synthetic=true` пациента.
5. `SafetyAlert` для С-003 — urgent, учебные лекарственные черновики — draft.
6. В `docker ps` нет публичных портов приложения или PostgreSQL.
7. Windows-браузер открывает AIDoctor через SSH-туннель.

Это критерии запуска *тестового контура*, не production.
