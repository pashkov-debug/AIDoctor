from collections.abc import Generator
from pathlib import Path

from app.core.config import settings
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def create_database_engine(database_url: str) -> Engine:
    engine = create_engine(
        database_url,
        future=True,
    )

    if database_url.startswith("sqlite"):
        event.listen(
            engine,
            "connect",
            _enable_sqlite_foreign_keys,
        )

    return engine


def _enable_sqlite_foreign_keys(
    dbapi_connection: object,
    connection_record: object,
) -> None:
    del connection_record

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def ensure_database_directory() -> None:
    database_path: Path = settings.database_path
    database_path.parent.mkdir(parents=True, exist_ok=True)


ensure_database_directory()

engine = create_database_engine(settings.database_url)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    session = SessionLocal()

    try:
        yield session
    finally:
        session.close()
