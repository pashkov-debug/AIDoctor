from collections.abc import Generator
from pathlib import Path

import pytest
from app.db.base import Base
from app.db.session import create_database_engine, get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def client(
    tmp_path: Path,
) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "patients-api.db"

    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"

    engine = create_database_engine(
        database_url,
    )

    Base.metadata.create_all(engine)

    testing_session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[Session, None, None]:
        session = testing_session_factory()

        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()

        Base.metadata.drop_all(engine)
        engine.dispose()


def create_patient(
    client: TestClient,
    *,
    alias: str = "P-017",
) -> dict:
    response = client.post(
        "/api/v1/patients",
        json={
            "alias": alias,
            "demographics": {
                "age_years": 34,
                "sex_at_birth": "female",
            },
        },
    )

    assert response.status_code == 201

    return response.json()


def test_create_patient(
    client: TestClient,
) -> None:
    patient = create_patient(client)

    assert patient["id"]
    assert patient["alias"] == "P-017"

    assert patient["demographics"] == {
        "age_years": 34,
        "sex_at_birth": "female",
    }

    assert patient["created_at"]


def test_get_patient(
    client: TestClient,
) -> None:
    created = create_patient(client)

    response = client.get(f"/api/v1/patients/{created['id']}")

    assert response.status_code == 200

    patient = response.json()

    assert patient["id"] == created["id"]
    assert patient["alias"] == "P-017"


def test_list_patients(
    client: TestClient,
) -> None:
    create_patient(
        client,
        alias="P-017",
    )

    create_patient(
        client,
        alias="P-018",
    )

    response = client.get("/api/v1/patients")

    assert response.status_code == 200

    payload = response.json()

    assert payload["total"] == 2
    assert len(payload["items"]) == 2


def test_search_patients(
    client: TestClient,
) -> None:
    create_patient(
        client,
        alias="P-017",
    )

    create_patient(
        client,
        alias="P-099",
    )

    response = client.get(
        "/api/v1/patients",
        params={
            "search": "017",
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["total"] == 1
    assert payload["items"][0]["alias"] == "P-017"


def test_unknown_patient_returns_404(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/patients/not-existing-id")

    assert response.status_code == 404

    assert response.json() == {
        "detail": "Patient not found",
    }
