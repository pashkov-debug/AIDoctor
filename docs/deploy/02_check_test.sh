#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")/.."
dc=(docker compose --env-file .env.test -f deploy/compose.test.yaml)

echo "=== Контейнеры ==="
"${dc[@]}" ps

echo "=== Проверка API ==="
curl --fail --silent --show-error --max-time 8   http://127.0.0.1:18080/api/v1/health |
  python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("status")=="ok" and d.get("environment")=="test",d; print(d)'

echo "=== Проверка страницы ==="
code="$(curl --silent --show-error --output /dev/null --write-out "%{http_code}"   --max-time 8 http://127.0.0.1:18080/app)"
test "$code" = "200" || { echo "Ошибка HTTP $code" >&2; exit 1; }
echo "HTTP 200"

echo "=== Синтетические карточки ==="
count="$("${dc[@]}" exec -T postgres psql -U aidoctor -d aidoctor_synthetic -At   -c "SELECT count(*) FROM patients WHERE demographics_json ->> 'synthetic' = 'true';")"
test "$count" = "3" || { echo "Ожидалось ровно три synthetic=true, получено: $count" >&2; exit 1; }
"${dc[@]}" exec -T postgres psql -U aidoctor -d aidoctor_synthetic -At   -c "SELECT alias FROM patients WHERE demographics_json ->> 'synthetic' = 'true' ORDER BY alias;"

echo "=== Учебные черновики и Safety Alert ==="
"${dc[@]}" exec -T postgres psql -U aidoctor -d aidoctor_synthetic -At   -c "SELECT status || ': ' || count(*)::text FROM clinical_orders WHERE source_reference LIKE 'synthetic:ui5:v1:candidate:%' GROUP BY status;"
"${dc[@]}" exec -T postgres psql -U aidoctor -d aidoctor_synthetic -At   -c "SELECT s.priority || '/' || s.status FROM safety_alerts s JOIN patients p ON p.id=s.patient_id WHERE p.alias LIKE '%С-003%';"
invalid="$("${dc[@]}" exec -T postgres psql -U aidoctor -d aidoctor_synthetic -At   -c "SELECT count(*) FROM clinical_orders WHERE source_reference LIKE 'synthetic:ui5:v1:candidate:%' AND status <> 'draft';")"
test "$invalid" = "0" || { echo "Ошибка: учебные назначения оказались утверждёнными!" >&2; exit 1; }
test "$("${dc[@]}" exec -T postgres psql -U aidoctor -d aidoctor_synthetic -At   -c "SELECT count(*) FROM safety_alerts s JOIN patients p ON p.id=s.patient_id WHERE p.alias LIKE '%С-003%' AND s.priority='urgent';")" = "1" || { echo "Ошибка: нет ожидаемого urgent Safety Alert"; exit 1; }

echo "=== Отдельная пустая БД для pytest ==="
"${dc[@]}" exec -T postgres psql -U aidoctor -d postgres -At   -c "SELECT datname FROM pg_database WHERE datname = 'aidoctor_test';"

echo "=== Опубликованные порты проекта ==="
docker ps --format 'table {{.Names}}\t{{.Ports}}' | grep -E 'NAMES|aidoctor-vds-test' || true
echo "УСПЕХ: закрытый AIDoctor отвечает, сценарии созданы."
