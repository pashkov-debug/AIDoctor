import pytest
from app.core.config import Settings
from app.db.session import create_database_engine


def test_postgres_url_is_required():
    with pytest.raises(ValueError):
        Settings(database_url="wrong://host/database")


def test_only_psycopg_is_accepted():
    with pytest.raises(ValueError):
        create_database_engine("unsupported://localhost/db")


def test_no_legacy_database_file_setting():
    assert "database_file" not in Settings.model_fields
