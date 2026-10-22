"""Функциональная интеграция настроек врача на выделенной PostgreSQL _test."""

from collections.abc import Generator

from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models.access import DoctorPatient, User
from app.models.doctor_settings import DoctorSettings, DoctorSettingsAudit
from app.models.patient import Patient
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


def test_doctor_settings_persistence_roles_versions_audit(pg_engine) -> None:
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as db:
        db.add_all(
            [
                User(
                    username="ui1_doctor",
                    password_hash=hash_password("secure-passphrase"),
                    role="doctor",
                ),
                User(
                    username="ui1_other",
                    password_hash=hash_password("secure-passphrase"),
                    role="doctor",
                ),
                User(
                    username="ui1_patient",
                    password_hash=hash_password("secure-passphrase"),
                    role="patient",
                ),
                User(
                    username="ui1_admin",
                    password_hash=hash_password("secure-passphrase"),
                    role="admin",
                ),
            ]
        )
        db.commit()
        doctor = db.scalar(select(User).where(User.username == "ui1_doctor"))
        # Синтетический пациент доступен только привязанному врачу.
        patient_record = Patient(alias="Синтетический пациент UI-1A", demographics_json={})
        db.add(patient_record)
        db.flush()
        db.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient_record.id))
        db.commit()
        synthetic_patient_id = patient_record.id

    def override_db() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:

            def login(name: str) -> dict[str, str]:
                r = client.post(
                    "/api/v1/auth/login",
                    json={
                        "username": name,
                        "password": "secure-passphrase",
                    },
                )
                assert r.status_code == 200, r.text
                return {"Authorization": "Bearer " + r.json()["access_token"]}

            doctor = login("ui1_doctor")
            other = login("ui1_other")
            patient = login("ui1_patient")
            admin = login("ui1_admin")
            # Используется существующий backend-контракт /patients, без дублирования ACL.
            mine = client.get("/api/v1/patients", headers=doctor)
            assert mine.status_code == 200
            assert [item["id"] for item in mine.json()["items"]] == [synthetic_patient_id]
            strangers = client.get("/api/v1/patients", headers=other)
            assert strangers.status_code == 200
            assert strangers.json()["items"] == []
            assert (
                client.get(f"/api/v1/patients/{synthetic_patient_id}", headers=other).status_code
                == 404
            )
            base_url = "/api/v1/doctors/me"
            assert client.get(base_url + "/settings", headers=patient).status_code == 403
            assert client.get(base_url + "/settings", headers=admin).status_code == 403
            assert client.get(base_url + "/doctor-context", headers=patient).status_code == 403
            assert (
                client.put(
                    base_url + "/settings/profile", headers=admin, json={"expected_version": 0}
                ).status_code
                == 403
            )
            initial = client.get(base_url + "/settings", headers=doctor)
            assert initial.status_code == 200
            assert initial.json()["version"] == 0
            assert initial.json()["clinical"]["rki_mode"] == "disabled"
            assert client.get(base_url + "/settings", headers=other).json()["version"] == 0

            profile = {
                "expected_version": 0,
                "full_name": "  Учебный врач  ",
                "specialty": "Психиатр",
                "institution": "Синтетическая клиника",
                "professional_info": "Только учебные данные",
                "contact_email": "demo@example.org",
            }
            p = client.put(base_url + "/settings/profile", headers=doctor, json=profile)
            assert p.status_code == 200, p.text
            assert p.json()["version"] == 1
            assert p.json()["profile"]["full_name"] == "Учебный врач"

            clinical = {
                "expected_version": 1,
                "practice_country": "Россия",
                "rki_mode": "consider_if_verified",
                "institution_type": "Амбулаторная клиника",
                "clinical_specialty": "Психиатрия",
            }
            c = client.put(base_url + "/settings/clinical", headers=doctor, json=clinical)
            assert c.status_code == 200, c.text
            assert c.json()["version"] == 2
            context = client.get(base_url + "/doctor-context", headers=doctor)
            assert context.status_code == 200
            data = context.json()
            assert data["profile_version"] == 2
            assert data["country"] == "Россия"
            assert data["rki"]["mode"] == "consider_if_verified"
            assert data["rki"]["source_verification"] == "required"
            assert data["specialty"] == "Психиатрия"
            assert "contact_email" not in data
            assert "full_name" not in data

            stale = client.put(base_url + "/settings/clinical", headers=doctor, json=clinical)
            assert stale.status_code == 409
            assert client.get(base_url + "/settings", headers=doctor).json()["version"] == 2
            repeat = client.put(
                base_url + "/settings/clinical",
                headers=doctor,
                json={**clinical, "expected_version": 2},
            )
            assert repeat.status_code == 200
            assert repeat.json()["version"] == 2  # идентичное сохранение не пишет аудит
            invalid = client.put(
                base_url + "/settings/clinical",
                headers=doctor,
                json={**clinical, "expected_version": 2, "rki_mode": "automatic"},
            )
            assert invalid.status_code == 422
            assert client.get(base_url + "/settings", headers=other).json()["version"] == 0
            assert client.get(base_url + "/doctor-context", headers=other).json()["country"] is None

            client.post("/api/v1/auth/logout", headers=doctor)
            assert client.get(base_url + "/settings", headers=doctor).status_code == 401
        with factory() as db:
            own = db.scalar(select(User).where(User.username == "ui1_doctor"))
            saved = db.get(DoctorSettings, own.id)
            assert saved.practice_country == "Россия"
            assert saved.version == 2
            events = db.scalars(
                select(DoctorSettingsAudit)
                .where(DoctorSettingsAudit.doctor_id == own.id)
                .order_by(DoctorSettingsAudit.to_version)
            ).all()
            assert len(events) == 2
            assert [event.section for event in events] == ["profile", "clinical"]
            assert [event.to_version for event in events] == [1, 2]
            assert events[0].actor_id == own.id
            assert "full_name" in events[0].changed_fields
    finally:
        app.dependency_overrides.clear()
