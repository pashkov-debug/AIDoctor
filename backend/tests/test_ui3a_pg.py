"""UI-3A: роли, версионирование, публикация и аудит на выделенной _test БД."""

from types import SimpleNamespace
from uuid import uuid4

from app.api.auth import current_user
from app.db.session import get_db
from app.main import create_app
from app.models.access import DoctorPatient, User
from app.models.clinical_order import ClinicalOrder, ClinicalOrderAudit
from app.models.patient import Patient
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


def test_lifecycle_visibility_roles_and_audit(pg_engine):
    with Session(pg_engine) as db:
        doc = User(username="dr3a", password_hash="x", role="doctor")
        other_doc = User(username="dr3b", password_hash="x", role="doctor")
        owner = User(username="patient3a", password_hash="x", role="patient")
        other_owner = User(username="patient3b", password_hash="x", role="patient")
        admin = User(username="admin3a", password_hash="x", role="admin")
        db.add_all([doc, other_doc, owner, other_owner, admin])
        db.flush()
        patient = Patient(
            alias="Синтетический А", user_id=owner.id, demographics_json={"synthetic": True}
        )
        second = Patient(
            alias="Синтетический Б", user_id=other_owner.id, demographics_json={"synthetic": True}
        )
        db.add_all([patient, second])
        db.flush()
        db.add(DoctorPatient(doctor_id=doc.id, patient_id=patient.id))
        db.commit()
        pid, did, uid = patient.id, doc.id, owner.id
        roles = {
            "doctor": SimpleNamespace(id=did, role="doctor"),
            "other_doctor": SimpleNamespace(id=other_doc.id, role="doctor"),
            "patient": SimpleNamespace(id=uid, role="patient"),
            "other_patient": SimpleNamespace(id=other_owner.id, role="patient"),
            "admin": SimpleNamespace(id=admin.id, role="admin"),
        }

    chosen = {"actor": roles["doctor"]}
    app = create_app()

    def db_override():
        with Session(pg_engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[current_user] = lambda: chosen["actor"]
    base = f"/api/v1/patients/{pid}/clinical-orders"
    own = "/api/v1/patients/me/clinical-orders"
    request_key = str(uuid4())
    draft = {"kind": "medication", "name": "Учебный препарат", "request_key": request_key}
    try:
        with TestClient(app) as client:
            chosen["actor"] = roles["patient"]
            assert client.get(own).json() == {"items": [], "total": 0}
            assert client.get(base).status_code == 403
            assert client.post(base, json=draft).status_code == 403

            chosen["actor"] = roles["other_doctor"]
            assert client.get(base).status_code == 404
            assert client.post(base, json=draft).status_code == 404

            chosen["actor"] = roles["admin"]
            assert client.get(base).status_code == 403

            chosen["actor"] = roles["doctor"]
            response = client.post(base, json=draft)
            assert response.status_code == 201, response.text
            item = response.json()
            oid = item["id"]
            assert item["status"] == "draft"
            assert item["dose_value"] is None
            assert client.post(base, json=draft).json()["id"] == oid
            assert client.post(base, json={**draft, "name": "Изменённый"}).status_code == 409
            assert client.get(base).status_code == 200

            chosen["actor"] = roles["patient"]
            assert client.get(own).json() == {"items": [], "total": 0}
            chosen["actor"] = roles["doctor"]
            approval = base + f"/{oid}/approve"
            confirm = {
                "expected_version": 1,
                "confirm_patient_visibility": True,
                "confirm_clinical_review": True,
            }
            assert client.post(approval, json=confirm).status_code == 422
            updated_fields = {
                **draft,
                "active_ingredient": "Синтетическое вещество",
                "dosage_form": "Учебная форма",
                "strength": "1 мг/ед.",
                "dose_value": "1.0000",
                "dose_unit": "мг",
                "route": "Учебный путь",
                "frequency_per_day": 2,
                "times_local": ["08:00", "20:00"],
                "timezone": "Europe/Moscow",
                "start_date": "2026-10-23",
                "duration_days": 7,
                "indication": "Учебная цель",
                "rationale": "Синтетический сценарий",
            }
            assert (
                client.put(
                    base + f"/{oid}", json={"expected_version": 2, "data": updated_fields}
                ).status_code
                == 409
            )
            resp = client.put(
                base + f"/{oid}", json={"expected_version": 1, "data": updated_fields}
            )
            assert resp.status_code == 200, resp.text
            assert resp.json()["version"] == 2
            assert client.post(approval, json=confirm).status_code == 409
            confirm["expected_version"] = 2
            assert (
                client.post(
                    approval, json={**confirm, "confirm_clinical_review": False}
                ).status_code
                == 422
            )
            approved = client.post(approval, json=confirm)
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "approved"
            assert approved.json()["version"] == 3
            assert client.post(approval, json=confirm).status_code == 409

            chosen["actor"] = roles["other_patient"]
            assert client.get(own).json()["total"] == 0
            chosen["actor"] = roles["patient"]
            public = client.get(own)
            assert public.status_code == 200
            public_json = public.json()
            assert public_json["total"] == 1
            assert public_json["items"][0]["name"] == "Учебный препарат"
            assert "rationale" not in str(public_json)
            assert "author_id" not in str(public_json)
            assert "request_key" not in str(public_json)
            assert "status" not in str(public_json)

            chosen["actor"] = roles["doctor"]
            cancel = base + f"/{oid}/cancel"
            assert (
                client.post(
                    cancel, json={"expected_version": 2, "reason": "Отмена теста"}
                ).status_code
                == 409
            )
            assert (
                client.post(
                    cancel, json={"expected_version": 3, "reason": "Отмена теста"}
                ).status_code
                == 200
            )
            assert (
                client.post(
                    cancel, json={"expected_version": 4, "reason": "Отмена повторно"}
                ).status_code
                == 409
            )
            chosen["actor"] = roles["patient"]
            assert client.get(own).json()["total"] == 0

        with Session(pg_engine) as db:
            assert db.scalar(select(func.count(ClinicalOrder.id))) == 1
            actions = db.scalars(
                select(ClinicalOrderAudit).order_by(ClinicalOrderAudit.version)
            ).all()
            assert [(e.action, e.version) for e in actions] == [
                ("draft_created", 1),
                ("draft_updated", 2),
                ("approved", 3),
                ("cancelled", 4),
            ]
            assert actions[2].snapshot_json["status"] == "approved"
            assert actions[3].snapshot_json["status"] == "cancelled"
    finally:
        app.dependency_overrides.clear()


def test_examination_and_revoked_link(pg_engine):
    with Session(pg_engine) as db:
        doctor = User(username="dr-exam", password_hash="x", role="doctor")
        patient_user = User(username="pt-exam", password_hash="x", role="patient")
        db.add_all([doctor, patient_user])
        db.flush()
        patient = Patient(alias="Синтетический", user_id=patient_user.id)
        db.add(patient)
        db.flush()
        relation = DoctorPatient(doctor_id=doctor.id, patient_id=patient.id)
        db.add(relation)
        db.commit()
        pid, uid, did, link_id = patient.id, patient_user.id, doctor.id, relation.id
    current = {"actor": SimpleNamespace(id=did, role="doctor")}
    app = create_app()

    def db_override():
        with Session(pg_engine) as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[current_user] = lambda: current["actor"]
    base = f"/api/v1/patients/{pid}/clinical-orders"
    try:
        with TestClient(app) as client:
            payload = {
                "request_key": str(uuid4()),
                "kind": "examination",
                "name": "Учебное обследование",
                "examination_details": "Детали синтетического исследования",
                "indication": "Синтетический сценарий",
                "rationale": "Учебная необходимость",
            }
            created = client.post(base, json=payload)
            assert created.status_code == 201, created.text
            oid = created.json()["id"]
            assert (
                client.post(
                    base + f"/{oid}/approve",
                    json={
                        "expected_version": 1,
                        "confirm_patient_visibility": True,
                        "confirm_clinical_review": True,
                    },
                ).status_code
                == 200
            )
            current["actor"] = SimpleNamespace(id=uid, role="patient")
            response = client.get("/api/v1/patients/me/clinical-orders").json()
            assert response["total"] == 1
            assert (
                response["items"][0]["examination_details"] == "Детали синтетического исследования"
            )
            current["actor"] = SimpleNamespace(id=did, role="doctor")
            with Session(pg_engine) as db:
                link = db.get(DoctorPatient, link_id)
                db.delete(link)
                db.commit()
            assert client.get(base).status_code == 404
            assert (
                client.post(
                    base + f"/{oid}/cancel",
                    json={
                        "expected_version": 2,
                        "reason": "Недоступно",
                    },
                ).status_code
                == 404
            )
    finally:
        app.dependency_overrides.clear()
