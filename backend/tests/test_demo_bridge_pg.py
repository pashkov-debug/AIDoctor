"""Фактический Context Builder на выделенной PostgreSQL тестовой базе."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models.history_event import HistoryEvent
from app.models.patient import Patient
from demo_bridge.contract import HISTORY_ID, PATIENT_ID, PUBLIC_ID, sha256_data
from demo_bridge.seed import seed_case
from demo_bridge.server import create_app


def test_bridge_real_context_builder_from_postgresql(pg_engine):
    with Session(pg_engine) as session, session.begin():
        assert seed_case(session) is True
        assert seed_case(session) is False

    client = TestClient(create_app(session_factory=sessionmaker(bind=pg_engine)))
    patient_response = client.get("/demo/v1/patient")
    context_response = client.get("/demo/v1/context")
    assert patient_response.status_code == 200
    assert context_response.status_code == 200
    patient = patient_response.json()
    context = context_response.json()
    assert patient["data"]["demo_id"] == PUBLIC_ID
    assert context["data"]["demo_id"] == PUBLIC_ID
    assert context["content_sha256"] == sha256_data(context["data"])
    clinical = context["data"]["clinical_context"]
    assert clinical["patient_id"] == PATIENT_ID
    assert len(clinical["items"]) == 4
    assert clinical["excluded_attachments_count"] == 0
    assert context["clinical_processing_allowed"] is False
    assert client.post("/demo/v1/context").status_code == 405

    # Фактическая подмена данных в PostgreSQL закрывает доступ.
    with Session(pg_engine) as session, session.begin():
        event = session.get(HistoryEvent, HISTORY_ID)
        event.fact_json = {"synthetic": False, "real_patient_note": "do not expose"}
    response = client.get("/demo/v1/context")
    assert response.status_code == 503
    assert "real_patient_note" not in response.text


def test_bridge_blocks_second_patient(pg_engine):
    with Session(pg_engine) as session, session.begin():
        seed_case(session)
        session.add(
            Patient(
                alias="DO-NOT-EXPOSE",
                demographics_json={"synthetic": False},
            )
        )
    client = TestClient(create_app(session_factory=sessionmaker(bind=pg_engine)))
    assert client.get("/demo/v1/patient").status_code == 503
