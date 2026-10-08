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
    database_path = tmp_path / "questionnaires.db"

    engine = create_database_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")

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


def create_patient_and_encounter(
    client: TestClient,
) -> tuple[dict, dict]:
    patient_response = client.post(
        "/api/v1/patients",
        json={
            "alias": "P-017",
            "demographics": {},
        },
    )

    assert patient_response.status_code == 201

    patient = patient_response.json()

    encounter_response = client.post(
        (f"/api/v1/patients/{patient['id']}/encounters"),
        json={
            "reason": "initial",
        },
    )

    assert encounter_response.status_code == 201

    return patient, encounter_response.json()


def test_questionnaire_score_is_deterministic(
    client: TestClient,
) -> None:
    patient, encounter = create_patient_and_encounter(client)

    response = client.post(
        (f"/api/v1/encounters/{encounter['id']}/questionnaires"),
        json={
            "scale_id": "DEMO_DEP_9",
            "item_scores": [
                0,
                1,
                2,
                3,
                0,
                1,
                2,
                3,
                1,
            ],
        },
    )

    assert response.status_code == 201

    result = response.json()

    assert result["patient_id"] == patient["id"]
    assert result["total_score"] == 13


def test_invalid_number_of_items_returns_422(
    client: TestClient,
) -> None:
    _, encounter = create_patient_and_encounter(client)

    response = client.post(
        (f"/api/v1/encounters/{encounter['id']}/questionnaires"),
        json={
            "scale_id": "DEMO_DEP_9",
            "item_scores": [1, 2],
        },
    )

    assert response.status_code == 422


def test_unknown_scale_returns_422(
    client: TestClient,
) -> None:
    _, encounter = create_patient_and_encounter(client)

    response = client.post(
        (f"/api/v1/encounters/{encounter['id']}/questionnaires"),
        json={
            "scale_id": "UNKNOWN",
            "item_scores": [1],
        },
    )

    assert response.status_code == 422


def test_questionnaire_creates_history_event(
    client: TestClient,
) -> None:
    patient, encounter = create_patient_and_encounter(client)

    response = client.post(
        (f"/api/v1/encounters/{encounter['id']}/questionnaires"),
        json={
            "scale_id": "DEMO_ANX_7",
            "item_scores": [
                1,
                1,
                1,
                1,
                1,
                1,
                1,
            ],
        },
    )

    assert response.status_code == 201

    history_response = client.get(f"/api/v1/patients/{patient['id']}/history-events")

    assert history_response.status_code == 200

    history = history_response.json()

    assert history["total"] == 1

    event = history["items"][0]

    assert event["category"] == "questionnaire"

    assert event["fact"] == {
        "scale_id": "DEMO_ANX_7",
        "total_score": 7,
    }

    assert event["source_ref"].startswith("local://questionnaire/")
