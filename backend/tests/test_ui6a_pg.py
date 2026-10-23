"""UI-6A: защищённый API и постоянные снимки. Только aidoctor_test."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.ai_workspace import AIRequest
from app.models.clinical_order import ClinicalOrder
from app.models.history_event import HistoryEvent
from app.models.patient import Patient
from app.services.ai_agent_context import current_orders_match
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def test_frozen_orders_read_only_and_authorized(pg_engine):
    with Session(pg_engine) as db:
        doctor = User(username="dr6a", role="doctor", password_hash="x")
        other = User(username="other6a", role="doctor", password_hash="x")
        patient_user = User(username="pt6a", role="patient", password_hash="x")
        db.add_all([doctor, other, patient_user])
        db.flush()
        patient = Patient(
            alias="UI6A synthetic",
            user_id=patient_user.id,
            demographics_json={"synthetic": True},
        )
        db.add(patient)
        db.flush()
        db.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        approved = ClinicalOrder(
            patient_id=patient.id,
            author_id=doctor.id,
            request_key=str(uuid4()),
            kind="medication",
            status="approved",
            version=1,
            name="Препарат A",
            active_ingredient="вещество A",
            approved_by_id=doctor.id,
            approved_at=datetime(2026, 10, 20, tzinfo=UTC),
        )
        draft = ClinicalOrder(
            patient_id=patient.id,
            author_id=doctor.id,
            request_key=str(uuid4()),
            kind="medication",
            status="draft",
            version=1,
            name="Сертралин (учебный проект)",
            active_ingredient="сертралин",
            dose_value=300,
            dose_unit="мг",
            source_reference="synthetic:ui5:v1:candidate:2",
        )
        db.add_all([approved, draft])
        db.add(
            HistoryEvent(
                patient_id=patient.id,
                category="self_report",
                source_ref="ui6a:reported-drug",
                occurred_at=datetime(2026, 10, 19, tzinfo=UTC),
                fact_json={"text": "Вымышленное сообщение о терапии", "synthetic": True},
            )
        )
        db.commit()
        pid, did = patient.id, draft.id
        actors = {
            "doctor": SimpleNamespace(id=doctor.id, role="doctor"),
            "other": SimpleNamespace(id=other.id, role="doctor"),
            "patient": SimpleNamespace(id=patient_user.id, role="patient"),
        }

    current = {"actor": actors["doctor"]}
    app = create_app()

    def session_override():
        with Session(pg_engine) as db:
            yield db

    app.dependency_overrides[get_db] = session_override
    app.dependency_overrides[current_user] = lambda: current["actor"]
    base = f"/api/v1/patients/{pid}/ai-requests"
    payload = {
        "request_key": str(uuid4()),
        "question": "Оцените проект лекарственного назначения пациента",
        "attachment_ids": [],
    }
    try:
        with TestClient(app) as client:
            created = client.post(base, json=payload)
            assert created.status_code == 201, created.text
            rid = created.json()["id"]
            assert created.json()["orders_review_available"] is True
            url = base + f"/{rid}/agent-context"
            response = client.get(url)
            assert response.status_code == 200, response.text
            assert response.headers["cache-control"] == "private, no-store"
            body = response.json()
            assert body["llm_dispatch_enabled"] is False
            assert body["patient_context"]["patient_id"] == pid
            assert len(body["patient_context"]["items"]) == 1
            assert body["doctor_context"]["schema_version"] == "doctor_context.v1"
            assert [x["status"] for x in body["orders_review"]["approved_orders"]] == ["approved"]
            drafts = body["orders_review"]["proposed_orders_for_review"]
            assert len(drafts) == 1 and drafts[0]["status"] == "draft"
            assert drafts[0]["dose_value"] in ("300", "300.0000")
            assert body["orders_review"]["clinical_safety_validated"] is False
            assert "correct_dose" not in str(body)

            current["actor"] = actors["patient"]
            assert client.get(url).status_code == 403
            current["actor"] = actors["other"]
            assert client.get(url).status_code == 404
            current["actor"] = actors["doctor"]

            with Session(pg_engine) as db:
                order = db.get(ClinicalOrder, did)
                order.dose_value = 200
                order.version += 1
                db.commit()
            still_frozen = client.get(url)
            assert still_frozen.status_code == 200
            assert still_frozen.json()["orders_review"] == body["orders_review"]
            with Session(pg_engine) as db:
                row = db.get(AIRequest, rid)
                assert current_orders_match(db, row) is False

            # Исторические запросы без снимка не "дополняем" свежими данными.
            with Session(pg_engine) as db:
                row = db.get(AIRequest, rid)
                row.review_orders_json = None
                row.review_orders_sha256 = None
                db.commit()
            assert client.get(url).status_code == 409
    finally:
        app.dependency_overrides.clear()
