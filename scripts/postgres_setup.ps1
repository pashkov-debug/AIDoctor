# Запуск из корня проекта. Требуется Docker Desktop.
$ErrorActionPreference = "Stop"
docker compose up -d postgres
docker compose exec -T postgres sh -c 'until pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do sleep 1; done'
Write-Host "PostgreSQL готов. Далее: python -m alembic -c alembic.ini upgrade head"
