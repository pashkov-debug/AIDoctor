"""Fail-closed проверка подключения к отдельной демонстрационной БД."""

import os

from sqlalchemy.engine import URL, make_url

DEMO_DATABASE_NAME = "aidoctor_demo"


def validated_demo_url(raw: str) -> URL:
    if not raw or len(raw) > 2048:
        raise ValueError("Укажи AIDOCTOR_DEMO_DB_URL для отдельной демонстрационной БД")
    try:
        url = make_url(raw)
    except Exception as exc:
        raise ValueError("Некорректный URL демонстрационной БД") from exc

    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {"127.0.0.1", "localhost"}
        or url.database != DEMO_DATABASE_NAME
        or url.username != "aidoctor"
        or url.query
        or url.port not in (None, 5432)
    ):
        raise ValueError(
            "Bridge разрешает только локальную PostgreSQL/psycopg "
            "с базой aidoctor_demo и пользователем aidoctor"
        )
    if not url.password:
        raise ValueError("Пароль демонстрационной БД обязателен")
    return url


def demo_url_from_env() -> URL:
    return validated_demo_url(os.environ.get("AIDOCTOR_DEMO_DB_URL", ""))
