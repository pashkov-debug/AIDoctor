"""Проверка реальных прав пациента на отдельной PostgreSQL _test."""

from collections.abc import Generator
from datetime import UTC, datetime

from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models.access import User
from app.models.patient import Patient
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


def test_patient_portal_isolated_and_soft_delete(pg_engine) -> None:
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as db:
        password_hash = hash_password("secure-passphrase")
        accounts = [
            ("ui1b_doctor", "doctor"),
            ("ui1b_admin", "admin"),
            ("ui1b_patient_a", "patient"),
            ("ui1b_patient_b", "patient"),
            ("ui1b_patient_unbound", "patient"),
            ("ui1b_patient_deleted", "patient"),
        ]
        db.add_all(
            [
                User(username=username, password_hash=password_hash, role=role)
                for username, role in accounts
            ]
        )
        db.flush()
        users = {u.username: u for u in db.scalars(select(User)).all()}
        mine = Patient(
            alias="Синтетический пациент А",
            demographics_json={"internal_note": "НЕ ПУБЛИКОВАТЬ"},
        )
        other = Patient(
            alias="Синтетический пациент Б",
            demographics_json={},
            user_id=users["ui1b_patient_b"].id,
        )
        deleted = Patient(
            alias="Удалённый синтетический пациент",
            demographics_json={},
            user_id=users["ui1b_patient_deleted"].id,
            deleted_at=datetime.now(UTC),
        )
        db.add_all([mine, other, deleted])
        db.commit()
        mine_id = mine.id
        other_id = other.id
        patient_a_id = users["ui1b_patient_a"].id

    def override_db() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            def login(username: str) -> dict[str, str]:
                response = client.post(
                    "/api/v1/auth/login",
                    json={"username": username, "password": "secure-passphrase"},
                )
                assert response.status_code == 200, response.text
                return {"Authorization": "Bearer " + response.json()["access_token"]}

            admin_headers = login("ui1b_admin")
            doctor_headers = login("ui1b_doctor")
            a_headers = login("ui1b_patient_a")
            b_headers = login("ui1b_patient_b")
            unbound_headers = login("ui1b_patient_unbound")
            deleted_headers = login("ui1b_patient_deleted")
            url = "/api/v1/patients/me/portal"

            assert client.get(url).status_code == 401
            assert client.get(url, headers=admin_headers).status_code == 403
            assert client.get(url, headers=doctor_headers).status_code == 403
            assert client.get(url, headers=a_headers).status_code == 404
            assert client.get(url, headers=unbound_headers).status_code == 404
            assert client.get(url, headers=deleted_headers).status_code == 404

            # Реальный действующий контракт привязки — только для admin.
            payload = {"patient_id": mine_id, "user_id": patient_a_id}
            assert (
                client.post(
                    "/api/v1/access/patient-account",
                    json=payload,
                    headers=a_headers,
                ).status_code
                == 403
            )
            linked = client.post(
                "/api/v1/access/patient-account",
                json=payload,
                headers=admin_headers,
            )
            assert linked.status_code == 200, linked.text

            own = client.get(url, headers=a_headers)
            assert own.status_code == 200, own.text
            data = own.json()
            assert data["schema_version"] == "patient_portal.v1"
            assert data["patient_id"] == mine_id
            assert data["alias"] == "Синтетический пациент А"
            assert set(data) == {"schema_version", "patient_id", "alias", "created_at"}
            assert "НЕ ПУБЛИКОВАТЬ" not in own.text

            other_result = client.get(url, headers=b_headers)
            assert other_result.status_code == 200
            assert other_result.json()["patient_id"] == other_id
            assert mine_id not in other_result.text

            # Существующий список пациентов также не возвращает чужие карточки.
            other_list = client.get("/api/v1/patients", headers=b_headers)
            assert other_list.status_code == 200
            assert [p["id"] for p in other_list.json()["items"]] == [other_id]

            assert (
                client.post("/api/v1/auth/logout", headers=a_headers).status_code == 204
            )
            assert client.get(url, headers=a_headers).status_code == 401
    finally:
        app.dependency_overrides.clear()
