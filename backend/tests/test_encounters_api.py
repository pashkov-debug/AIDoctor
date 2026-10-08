from collections.abc import Generator
from pathlib import Path

import pytest
from app.db.base import Base
from app.db.session import (
    create_database_engine,
    get_db,
)
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture
def client(
    tmp_path: Path,
) -> Generator[TestClient, None, None]:
    database_path = tmp_path / "encounters-api.db"

    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"

    engine = create_database_engine(database_url)

    Base.metadata.create_all(engine)

    session_factory = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_get_db() -> Generator[
        Session,
        None,
        None,
    ]:
        session = session_factory()

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
) -> dict:
    response = client.post(
        "/api/v1/patients",
        json={
            "alias": "P-017",
            "demographics": {
                "age_years": 34,
                "sex_at_birth": "female",
            },
        },
    )

    assert response.status_code == 201

    return response.json()


def test_create_encounter(
    client: TestClient,
) -> None:
    patient = create_patient(client)

    response = client.post(
        (f"/api/v1/patients/{patient['id']}/encounters"),
        json={
            "reason": "initial",
            "complaints": [
                "low_mood",
                "anxiety",
            ],
            "functional_impact": "moderate",
            "clinician_question": ("Уточнить дальнейшую маршрутизацию"),
        },
    )

    assert response.status_code == 201

    encounter = response.json()

    assert encounter["patient_id"] == patient["id"]
    assert encounter["reason"] == "initial"

    assert encounter["complaints"] == [
        "low_mood",
        "anxiety",
    ]

    assert encounter["functional_impact"] == "moderate"

    assert encounter["status"] == "draft"


def test_get_encounter(
    client: TestClient,
) -> None:
    patient = create_patient(client)

    created = client.post(
        (f"/api/v1/patients/{patient['id']}/encounters"),
        json={
            "reason": "follow_up",
        },
    ).json()

    response = client.get(f"/api/v1/encounters/{created['id']}")

    assert response.status_code == 200

    encounter = response.json()

    assert encounter["id"] == created["id"]
    assert encounter["reason"] == "follow_up"


def test_list_patient_encounters(
    client: TestClient,
) -> None:
    patient = create_patient(client)

    for reason in [
        "initial",
        "follow_up",
    ]:
        response = client.post(
            (f"/api/v1/patients/{patient['id']}/encounters"),
            json={
                "reason": reason,
            },
        )

        assert response.status_code == 201

    response = client.get(f"/api/v1/patients/{patient['id']}/encounters")

    assert response.status_code == 200

    payload = response.json()

    assert payload["total"] == 2
    assert len(payload["items"]) == 2


def test_create_encounter_for_unknown_patient_returns_404(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/patients/not-existing/encounters",
        json={
            "reason": "initial",
        },
    )

    assert response.status_code == 404

    assert response.json() == {
        "detail": "Patient not found",
    }


def test_unknown_encounter_returns_404(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/encounters/not-existing")

    assert response.status_code == 404

    assert response.json() == {
        "detail": "Encounter not found",
    }
