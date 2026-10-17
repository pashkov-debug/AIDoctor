# Создаёт отдельную тестовую БД. Удаляет лишь БД aidoctor_test, если потребуется.
$ErrorActionPreference = "Stop"
docker compose exec -T postgres psql -U aidoctor -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='aidoctor_test'" | ForEach-Object {
    if ($_ -match '1') { $script:exists = $true }
}
if (-not $exists) {
    docker compose exec -T postgres psql -U aidoctor -d postgres -c "CREATE DATABASE aidoctor_test"
}
$env:TEST_DATABASE_URL="postgresql+psycopg://aidoctor:aidoctor_dev@127.0.0.1:5432/aidoctor_test"
Write-Host "TEST_DATABASE_URL задан только для текущего PowerShell."
