"""Интеграционные тесты используют только выделенную PostgreSQL-базу."""

import os
from urllib.parse import urlsplit

import pytest
from app.db.base import Base
from app.db.session import create_database_engine


@pytest.fixture
def pg_engine():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Требуется TEST_DATABASE_URL для PostgreSQL integration tests")
    parsed = urlsplit(url)
    database_name = parsed.path.lstrip("/")
    if (
        parsed.scheme != "postgresql+psycopg"
        or not database_name.endswith("_test")
        or parsed.hostname not in ("localhost", "127.0.0.1")
    ):
        pytest.fail("TEST_DATABASE_URL должен указывать на локальную БД с суффиксом _test")
    engine = create_database_engine(url)
    try:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
