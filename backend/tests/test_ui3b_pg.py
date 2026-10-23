"""PostgreSQL: роли, изоляция, версии, повторы и атомарный Safety Alert."""

from types import SimpleNamespace
from uuid import uuid4

from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from app.models.questionnaire_assignment import (
    QuestionnaireAssignment,
    QuestionnaireAssignmentAudit,
    QuestionnaireSubmission,
)
from app.models.safety_alert import SafetyAlert
from app.models.safety_outbox import SafetyOutbox
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def test_assign_complete_trend_security_and_alert(pg_engine):
    with Session(pg_engine) as db:
        doc = User(username="dr3b", password_hash="x", role="doctor")
        stranger_doc = User(username="dr3bOther", password_hash="x", role="doctor")
        patient_user = User(username="pt3b", password_hash="x", role="patient")
        stranger = User(username="pt3bOther", password_hash="x", role="patient")
        admin = User(username="admin3b", password_hash="x", role="admin")
        db.add_all([doc, stranger_doc, patient_user, stranger, admin])
        db.flush()
        patient = Patient(
            alias="Синтетический 3B", user_id=patient_user.id, demographics_json={"synthetic": True}
        )
        other = Patient(alias="Иной", user_id=stranger.id)
        db.add_all([patient, other])
        db.flush()
        db.add(DoctorPatient(doctor_id=doc.id, patient_id=patient.id))
        db.commit()
        pid = patient.id
        ids = {
            key: SimpleNamespace(id=obj.id, role=obj.role)
            for key, obj in {
                "doctor": doc,
                "stranger_doc": stranger_doc,
                "patient": patient_user,
                "stranger": stranger,
                "admin": admin,
            }.items()
        }

    chosen = {"actor": ids["doctor"]}
    app = create_app()

    def db_override():
        with Session(pg_engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[current_user] = lambda: chosen["actor"]
    base = f"/api/v1/patients/{pid}/questionnaire-assignments"
    own = "/api/v1/patients/me/questionnaire-assignments"
    key = str(uuid4())
    payload = {"test_id": "DEMO_DEP_9", "request_key": key}
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/questionnaire-catalog").status_code == 200
            chosen["actor"] = ids["patient"]
            assert client.get(base).status_code == 403
            assert client.post(base, json=payload).status_code == 403
            assert client.get(own).json() == []
            chosen["actor"] = ids["stranger_doc"]
            assert client.get(base).status_code == 404
            assert client.post(base, json=payload).status_code == 404
            chosen["actor"] = ids["admin"]
            assert client.post(base, json=payload).status_code == 403
            assert client.get("/api/v1/questionnaire-catalog").status_code == 403
            chosen["actor"] = ids["doctor"]
            created = client.post(base, json=payload)
            assert created.status_code == 201, created.text
            item = created.json()
            assert item["status"] == "assigned"
            assert item["test_version"] == "demo-1"
            assert client.post(base, json=payload).json()["id"] == item["id"]
            assert (
                client.post(
                    base,
                    json={
                        **payload,
                        "test_id": "DEMO_ANX_7",
                    },
                ).status_code
                == 409
            )
            submit = own + f"/{item['id']}/submit"
            chosen["actor"] = ids["stranger"]
            assert client.get(own).json() == []
            assert (
                client.post(
                    submit,
                    json={
                        "expected_revision": 1,
                        "answers": [0] * 9,
                    },
                ).status_code
                == 404
            )
            chosen["actor"] = ids["patient"]
            assert len(client.get(own).json()) == 1
            assert (
                client.post(
                    submit,
                    json={
                        "expected_revision": 1,
                        "answers": [0] * 8,
                    },
                ).status_code
                == 422
            )
            assert (
                client.post(
                    submit,
                    json={
                        "expected_revision": 2,
                        "answers": [0] * 8 + [1],
                    },
                ).status_code
                == 409
            )
            completed = client.post(
                submit,
                json={
                    "expected_revision": 1,
                    "answers": [0] * 8 + [1],
                },
            )
            assert completed.status_code == 200, completed.text
            assert completed.json()["result"]["critical_flag"] is True
            assert completed.json()["result"]["total_score"] == 1
            assert completed.json()["revision"] == 2
            assert (
                client.post(
                    submit,
                    json={
                        "expected_revision": 1,
                        "answers": [0] * 8 + [1],
                    },
                ).status_code
                == 200
            )
            assert (
                client.post(
                    submit,
                    json={
                        "expected_revision": 1,
                        "answers": [0] * 9,
                    },
                ).status_code
                == 409
            )
            chosen["actor"] = ids["doctor"]
            assert (
                client.post(
                    base + f"/{item['id']}/cancel",
                    json={
                        "expected_revision": 2,
                        "reason": "После завершения",
                    },
                ).status_code
                == 409
            )
            detail = client.get(base).json()
            assert detail[0]["alert_id"] is not None
            assert detail[0]["result"]["total_score"] == 1
            second = client.post(
                base,
                json={
                    "test_id": "DEMO_DEP_9",
                    "request_key": str(uuid4()),
                },
            )
            assert second.status_code == 201
            sid = second.json()["id"]
            cancelled = client.post(
                base + f"/{sid}/cancel",
                json={
                    "expected_revision": 1,
                    "reason": "Отмена учебного назначения",
                },
            )
            assert cancelled.status_code == 200
            chosen["actor"] = ids["patient"]
            assert len(client.get(own).json()) == 1
            assert (
                client.post(
                    own + f"/{sid}/submit",
                    json={
                        "expected_revision": 1,
                        "answers": [0] * 9,
                    },
                ).status_code
                == 409
            )
        with Session(pg_engine) as db:
            assert db.scalar(select(func.count(QuestionnaireAssignment.id))) == 2
            assert db.scalar(select(func.count(QuestionnaireSubmission.id))) == 1
            alert = db.scalar(select(SafetyAlert))
            assert alert is not None and alert.priority == "urgent"
            assert alert.status == "open" and alert.patient_id == pid
            assert db.scalar(select(func.count(SafetyOutbox.id))) >= 1
            actions = db.scalars(
                select(QuestionnaireAssignmentAudit)
                .where(
                    QuestionnaireAssignmentAudit.assignment_id == item["id"],
                )
                .order_by(QuestionnaireAssignmentAudit.revision)
            ).all()
            assert [x.action for x in actions] == ["assigned", "completed"]
    finally:
        app.dependency_overrides.clear()
