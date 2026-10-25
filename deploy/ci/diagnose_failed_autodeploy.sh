#!/usr/bin/env bash
# AIDoctor: проверка ПОСЛЕ отката (только чтение; БД и Docker не изменяются).
set -u
repo="/opt/aidoctor/git-checkout"
runtime="/usr/local/sbin/aidoctor-autodeploy"
cd "$repo" || exit 1
dc=(docker compose --env-file .env.test -f deploy/compose.test.yaml)
echo "=== Текущий checkout ==="
git rev-parse --short HEAD
echo "=== Установленный автодеплой: проверки после запуска ==="
if [[ -r "$runtime" ]]; then
  grep -nE 'patient_count|draft_leaks|/app|api/v1/health' "$runtime" || true
else
  echo "Скрипт недоступен для чтения: $runtime"
fi
echo "=== Проверка API /api/v1/health ==="
curl --silent --show-error --max-time 12 http://127.0.0.1:18080/api/v1/health || true
printf '\\n'
echo "=== HTTP-код /app ==="
curl --silent --show-error --output /dev/null --write-out '%{http_code}\\n' --max-time 12 \
  http://127.0.0.1:18080/app || true
echo "=== Синтетические пациенты (учитывается именно поле synthetic) ==="
"${dc[@]}" exec -T postgres psql -X -v ON_ERROR_STOP=1 -U aidoctor -d aidoctor_synthetic -At \
  -c "SELECT count(*) FROM patients WHERE demographics_json ->> 'synthetic' = 'true';" || true
echo "=== Утечки статусов учебных лекарственных черновиков ==="
"${dc[@]}" exec -T postgres psql -X -v ON_ERROR_STOP=1 -U aidoctor -d aidoctor_synthetic -At \
  -c "SELECT count(*) FROM clinical_orders WHERE source_reference LIKE 'synthetic:ui5:v1:candidate:%' AND status <> 'draft';" || true
echo "=== Конец диагностики. Никаких изменений не выполнено. ==="
