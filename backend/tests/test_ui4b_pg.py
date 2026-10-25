"""UI-4B PostgreSQL: тестовое поэлементное согласование, аудит, изоляция."""

from types import SimpleNamespace
from uuid import uuid4

from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.ai_review import AIReviewCase, AIReviewEvent, AIReviewVersion
from app.models.clinical_order import ClinicalOrder, ClinicalOrderAudit
from app.models.patient import Patient
from app.models.questionnaire_assignment import QuestionnaireAssignment
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def test_synthetic_review_approval(monkeypatch, pg_engine):
    monkeypatch.setenv("AIDOCTOR_ALLOW_SYNTHETIC_AI_DRAFTS", "1")
    with Session(pg_engine) as db:
        doctor = User(username="dr4b", role="doctor", password_hash="x")
        stranger = User(username="otherdr4b", role="doctor", password_hash="x")
        patient_user = User(username="pt4b", role="patient", password_hash="x")
        db.add_all([doctor, stranger, patient_user])
        db.flush()
        patient = Patient(
            alias="Синтетический UI-4B",
            user_id=patient_user.id,
            demographics_json={"synthetic": True},
        )
        real = Patient(alias="Не синтетический", demographics_json={})
        db.add_all([patient, real])
        db.flush()
        db.add_all(
            [
                DoctorPatient(doctor_id=doctor.id, patient_id=patient.id),
                DoctorPatient(doctor_id=doctor.id, patient_id=real.id),
            ]
        )
        db.commit()
        ids = (patient.id, real.id)
        actors = {
            key: SimpleNamespace(id=value.id, role=value.role)
            for key, value in {
                "doctor": doctor,
                "stranger": stranger,
                "patient": patient_user,
            }.items()
        }

    chosen = {"actor": actors["doctor"]}
    app = create_app()

    def db_override():
        with Session(pg_engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[current_user] = lambda: chosen["actor"]
    try:
        with TestClient(app) as client:
            pid, realid = ids
            req = client.post(
                f"/api/v1/patients/{pid}/ai-requests",
                json={
                    "request_key": str(uuid4()),
                    "question": "Учебный структурированный анализ истории",
                },
            )
            assert req.status_code == 201, req.text
            url = f"/api/v1/patients/{pid}/ai-requests/{req.json()['id']}/review"
            a, b, c, t = [str(uuid4()) for _ in range(4)]

            def drug(name):
                return {
                    "request_key": str(uuid4()),
                    "kind": "medication",
                    "name": name,
                    "active_ingredient": "Вымышленное вещество",
                    "dosage_form": "условная",
                    "strength": "учебная",
                    "dose_value": "1",
                    "dose_unit": "условная",
                    "route": "учебный",
                    "frequency_per_day": 1,
                    "times_local": ["09:00"],
                    "timezone": "Europe/Moscow",
                    "start_date": "2026-10-23",
                    "duration_days": 1,
                    "indication": "Тестовый сценарий",
                    "rationale": "Не клинический источник",
                }

            proposals = [
                {
                    "id": a,
                    "kind": "medication",
                    "order": drug("Учебный препарат А"),
                    "alternative_group": "alternative1",
                },
                {
                    "id": b,
                    "kind": "medication",
                    "order": drug("Учебный препарат Б"),
                    "alternative_group": "alternative1",
                },
                {
                    "id": c,
                    "kind": "examination",
                    "order": {
                        "request_key": str(uuid4()),
                        "kind": "examination",
                        "name": "Учебное обследование",
                        "examination_details": "Синтетическое",
                        "indication": "Тест",
                        "rationale": "Тест",
                    },
                },
                {"id": t, "kind": "demo_test", "test_id": "DEMO_ANX_7"},
            ]
            chosen["actor"] = actors["patient"]
            assert client.get(url).status_code == 403
            assert (
                client.post(
                    url, json={"origin": "synthetic_manual_test", "proposals": proposals}
                ).status_code
                == 403
            )
            chosen["actor"] = actors["stranger"]
            assert client.get(url).status_code == 404
            chosen["actor"] = actors["doctor"]
            assert (
                client.post(
                    f"/api/v1/patients/{realid}/ai-requests",
                    json={
                        "request_key": str(uuid4()),
                        "question": "Вопрос для другого пациента",
                    },
                ).status_code
                == 201
            )
            real_req = client.get(f"/api/v1/patients/{realid}/ai-requests").json()[0]["id"]
            # Ручное согласование больше не зависит от synthetic=true.
            assert (
                client.post(
                    f"/api/v1/patients/{realid}/ai-requests/{real_req}/review",
                    json={
                        "origin": "synthetic_manual_test",
                        "proposals": proposals,
                    },
                ).status_code
                == 201
            )
            imported = client.post(
                url, json={"origin": "synthetic_manual_test", "proposals": proposals}
            )
            assert imported.status_code == 201, imported.text
            assert imported.json()["version"] == 1
            assert (
                client.post(
                    url, json={"origin": "synthetic_manual_test", "proposals": proposals}
                ).status_code
                == 409
            )
            revised = client.post(
                url,
                json={
                    "origin": "synthetic_manual_test",
                    "expected_version": 1,
                    "proposals": proposals,
                },
            )
            assert revised.status_code == 201
            assert revised.json()["versions_available"] == [1, 2]
            api_preview = url + "/preview"
            wrong = client.post(
                api_preview, json={"expected_version": 1, "selections": [{"proposal_id": a}]}
            )
            assert wrong.status_code == 409
            alternatives = client.post(
                api_preview,
                json={
                    "expected_version": 2,
                    "selections": [{"proposal_id": a}, {"proposal_id": b}],
                },
            )
            assert alternatives.status_code == 422
            edited_order = {**proposals[0]["order"], "duration_days": 2}
            selections = [
                {"proposal_id": a, "order": edited_order},
                {"proposal_id": c},
                {"proposal_id": t},
            ]
            draft_action = {
                "expected_version": 2,
                "selections": selections,
                "edit_reason": "Врач исправил длительность",
            }
            preview = client.post(api_preview, json=draft_action)
            assert preview.status_code == 200, preview.text
            changes = preview.json()["changes"]
            assert len(changes) == 3
            assert changes[0]["edited"]
            assert changes[0]["final"]["duration_days"] == 2
            assert changes[0]["final"]["request_key"] != edited_order["request_key"]
            chosen["actor"] = actors["patient"]
            assert client.get("/api/v1/patients/me/clinical-orders").json()["total"] == 0
            chosen["actor"] = actors["doctor"]
            invalid_hash = client.post(
                url + "/approve",
                json={
                    **draft_action,
                    "preview_sha256": "0" * 64,
                    "confirm_patient_visibility": True,
                    "confirm_clinical_review": True,
                },
            )
            assert invalid_hash.status_code == 409
            assert client.get(f"/api/v1/patients/{pid}/clinical-orders").json() == []
            approved = client.post(
                url + "/approve",
                json={
                    **draft_action,
                    "preview_sha256": preview.json()["preview_sha256"],
                    "confirm_patient_visibility": True,
                    "confirm_clinical_review": True,
                },
            )
            assert approved.status_code == 200, approved.text
            assert len(approved.json()["records"]) == 3
            assert (
                client.post(
                    url + "/approve",
                    json={
                        **draft_action,
                        "preview_sha256": preview.json()["preview_sha256"],
                        "confirm_patient_visibility": True,
                        "confirm_clinical_review": True,
                    },
                ).status_code
                == 200
            )
            assert (
                client.post(
                    url + "/reject",
                    json={
                        "expected_version": 2,
                        "reason": "Нет",
                    },
                ).status_code
                == 409
            )
            chosen["actor"] = actors["patient"]
            public_orders = client.get("/api/v1/patients/me/clinical-orders")
            assert public_orders.status_code == 200
            assert public_orders.json()["total"] == 2
            public_tests = client.get("/api/v1/patients/me/questionnaire-assignments")
            assert public_tests.status_code == 200
            assert len(public_tests.json()) == 1

        with Session(pg_engine) as db:
            assert db.scalar(select(func.count(ClinicalOrder.id))) == 2
            assert db.scalar(select(func.count(ClinicalOrderAudit.id))) == 2
            assert db.scalar(select(func.count(QuestionnaireAssignment.id))) == 1
            assert db.scalar(select(func.count(AIReviewCase.id))) == 2
            assert db.scalar(select(func.count(AIReviewVersion.id))) == 3
            assert db.scalar(select(func.count(AIReviewEvent.id))) == 4
    finally:
        app.dependency_overrides.clear()
