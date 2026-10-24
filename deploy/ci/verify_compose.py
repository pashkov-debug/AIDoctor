"""Защитные инварианты существующего закрытого тестового Docker Compose."""

from __future__ import annotations

import json
import sys
from typing import Any


def validate(config: dict[str, Any]) -> None:
    if config.get("name") != "aidoctor-vds-test":
        raise ValueError("Изменилось имя Compose-проекта: возможна подмена Docker-томов")
    services = config.get("services") or {}
    if set(services) not in ({"postgres", "app"}, {"postgres", "app", "seed"}):
        raise ValueError("Изменён состав сервисов: требуется отдельная проверка")
    postgres, app = (services[name] for name in ("postgres", "app"))
    seed = services.get("seed") or {}
    if postgres.get("image") != "postgres:16":
        raise ValueError("Изменился образ PostgreSQL")
    if postgres.get("ports") or seed.get("ports"):
        raise ValueError("PostgreSQL/seed не должны иметь опубликованных портов")

    ports = app.get("ports") or []
    if len(ports) != 1:
        raise ValueError("FastAPI должен публиковать только один localhost-порт")
    port = ports[0]
    if not isinstance(port, dict) or (
        str(port.get("host_ip")) != "127.0.0.1"
        or str(port.get("published")) != "18080"
        or str(port.get("target")) != "8000"
        or port.get("protocol", "tcp") != "tcp"
    ):
        raise ValueError("FastAPI не должен быть доступен через публичный IP")

    def has_volume(service: dict, destination: str, source: str) -> bool:
        for volume in service.get("volumes") or []:
            if not isinstance(volume, dict):
                continue
            if volume.get("type") != "volume" or volume.get("target") != destination:
                continue
            if volume.get("source") in (source, f"aidoctor-vds-test_{source}"):
                return True
        return False

    if not has_volume(postgres, "/var/lib/postgresql/data", "pg_synthetic"):
        raise ValueError("Изменено постоянное хранилище PostgreSQL")
    if not has_volume(app, "/opt/aidoctor/data", "attachments_test"):
        raise ValueError("Изменено постоянное хранилище вложений")

    env = app.get("environment") or {}
    if isinstance(env, list):
        env = dict(item.split("=", 1) for item in env)
    if env.get("APP_ENV") != "test":
        raise ValueError("Тестовая среда не должна переключаться в production")
    db_url = env.get("DATABASE_URL", "")
    if "@postgres:5432/aidoctor_synthetic" not in db_url:
        raise ValueError("Неверная целевая БД; ожидается aidoctor_synthetic")
    if env.get("AIDOCTOR_ALLOW_SYNTHETIC_AI_DRAFTS", "0") != "0":
        raise ValueError("Автоутверждение/учебный режим AI не должен включаться")
    if (config.get("volumes") or {}).keys() < {"pg_synthetic", "attachments_test"}:
        raise ValueError("Отсутствуют защищаемые именованные тома")


def main() -> None:
    try:
        validate(json.load(sys.stdin))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"ОШИБКА конфигурации Compose: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("OK: тестовый Compose сохранил БД, тома и закрытые порты.")


if __name__ == "__main__":
    main()
