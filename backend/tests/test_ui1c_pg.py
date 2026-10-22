"""PostgreSQL _test: роли, аудит, связи, привязки и регрессия ACL."""

from collections.abc import Generator

from app.core.security import hash_password
from app.db.session import get_db
from app.main import app
from app.models.access import User
from app.models.admin_audit import AdminAuditEvent
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


def test_admin_end_to_end_and_isolation(pg_engine) -> None:
    factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    with factory() as db:
        db.add_all(
            [
                User(
                    username="ui1c_admin",
                    role="admin",
                    password_hash=hash_password("secure-passphrase"),
                ),
                User(
                    username="ui1c_doctor",
                    role="doctor",
                    password_hash=hash_password("secure-passphrase"),
                ),
                User(
                    username="ui1c_patient",
                    role="patient",
                    password_hash=hash_password("secure-passphrase"),
                ),
            ]
        )
        db.commit()

    def override_db() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:

            def login(username: str) -> dict[str, str]:
                result = client.post(
                    "/api/v1/auth/login",
                    json={
                        "username": username,
                        "password": "secure-passphrase",
                    },
                )
                assert result.status_code == 200, result.text
                return {"Authorization": f"Bearer {result.json()['access_token']}"}

            admin = login("ui1c_admin")
            doctor = login("ui1c_doctor")
            patient = login("ui1c_patient")
            base = "/api/v1/admin"
            for headers in (doctor, patient):
                for uri in ("/users", "/patients", "/links", "/audit"):
                    assert client.get(base + uri, headers=headers).status_code == 403
                assert (
                    client.post(
                        base + "/users",
                        headers=headers,
                        json={
                            "username": "intruder",
                            "password": "secure-passphrase",
                            "role": "doctor",
                        },
                    ).status_code
                    == 403
                )
                assert (
                    client.post(
                        "/api/v1/access/link",
                        headers=headers,
                        json={
                            "doctor_id": "X",
                            "patient_id": "Y",
                        },
                    ).status_code
                    == 403
                )
                assert (
                    client.post(
                        "/api/v1/access/patient-account",
                        headers=headers,
                        json={
                            "user_id": "X",
                            "patient_id": "Y",
                        },
                    ).status_code
                    == 403
                )
            assert client.get(base + "/audit", headers=admin).json() == []
            accounts = client.get(base + "/users", headers=admin)
            assert accounts.status_code == 200
            assert {u["username"] for u in accounts.json()} == {
                "ui1c_admin",
                "ui1c_doctor",
                "ui1c_patient",
            }
            assert all("password" not in str(u) for u in accounts.json())

            created_user = client.post(
                base + "/users",
                headers=admin,
                json={
                    "username": "ui1c_extra",
                    "password": "very-secret-password",
                    "role": "patient",
                },
            )
            assert created_user.status_code == 201, created_user.text
            assert created_user.json()["role"] == "patient"
            assert "password" not in created_user.text
            assert (
                client.post(
                    base + "/users",
                    headers=admin,
                    json={
                        "username": "ui1c_extra",
                        "password": "very-secret-password",
                        "role": "patient",
                    },
                ).status_code
                == 409
            )
            assert (
                client.post(
                    base + "/users",
                    headers=admin,
                    json={
                        "username": "ui1c_second_admin",
                        "password": "secure-passphrase",
                        "role": "admin",
                    },
                ).status_code
                == 422
            )

            created_patient = client.post(
                base + "/synthetic-patients",
                headers=admin,
                json={"alias": "  Синтетический С-001  "},
            )
            assert created_patient.status_code == 201, created_patient.text
            patient_id = created_patient.json()["id"]
            assert created_patient.json()["synthetic"] is True
            assert created_patient.json()["alias"] == "Синтетический С-001"

            other = client.post(
                base + "/synthetic-patients", headers=admin, json={"alias": "Синтетический С-002"}
            )
            assert other.status_code == 201
            other_id = other.json()["id"]

            cards = client.get(base + "/patients", headers=admin).json()
            assert {x["id"] for x in cards} == {patient_id, other_id}
            assert all(x["synthetic"] for x in cards)
            assert client.get("/api/v1/patients", headers=doctor).json()["items"] == []

            doctor_id = next(u["id"] for u in accounts.json() if u["username"] == "ui1c_doctor")
            patient_account_id = next(
                u["id"] for u in accounts.json() if u["username"] == "ui1c_patient"
            )
            link_url = "/api/v1/access/link"
            payload = {"doctor_id": doctor_id, "patient_id": patient_id}
            linked = client.post(link_url, headers=admin, json=payload)
            assert linked.status_code == 201, linked.text
            link_id = linked.json()["id"]
            assert client.post(link_url, headers=admin, json=payload).json()["id"] == link_id

            mine = client.get("/api/v1/patients", headers=doctor)
            assert mine.status_code == 200
            assert [item["id"] for item in mine.json()["items"]] == [patient_id]
            assert client.get(f"/api/v1/patients/{other_id}", headers=doctor).status_code == 404

            bind = client.post(
                "/api/v1/access/patient-account",
                headers=admin,
                json={
                    "patient_id": patient_id,
                    "user_id": patient_account_id,
                },
            )
            assert bind.status_code == 200, bind.text
            assert (
                client.post(
                    "/api/v1/access/patient-account",
                    headers=admin,
                    json={
                        "patient_id": patient_id,
                        "user_id": patient_account_id,
                    },
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/api/v1/access/patient-account",
                    headers=admin,
                    json={
                        "patient_id": patient_id,
                        "user_id": created_user.json()["id"],
                    },
                ).status_code
                == 409
            )
            assert (
                client.post(
                    "/api/v1/access/patient-account",
                    headers=admin,
                    json={
                        "patient_id": other_id,
                        "user_id": patient_account_id,
                    },
                ).status_code
                == 409
            )
            own_portal = client.get("/api/v1/patients/me/portal", headers=patient)
            assert own_portal.status_code == 200
            assert own_portal.json()["patient_id"] == patient_id
            assert other_id not in own_portal.text
            assert client.get(base + "/links", headers=admin).json()[0]["id"] == link_id
            assert client.delete(base + "/links/" + link_id, headers=doctor).status_code == 403
            assert client.delete(base + "/links/" + link_id, headers=admin).status_code == 204
            assert client.delete(base + "/links/" + link_id, headers=admin).status_code == 404
            assert client.get(base + "/links", headers=admin).json() == []
            assert client.get("/api/v1/patients", headers=doctor).json()["items"] == []
            # Отзыв врача не разрывает собственный кабинет пациента.
            assert client.get("/api/v1/patients/me/portal", headers=patient).status_code == 200

            events = client.get(base + "/audit", headers=admin)
            assert events.status_code == 200
            actions = [e["action"] for e in events.json()]
            assert sorted(actions) == sorted(
                [
                    "user_created",
                    "synthetic_patient_created",
                    "synthetic_patient_created",
                    "doctor_patient_linked",
                    "patient_account_bound",
                    "doctor_patient_unlinked",
                ]
            )
            assert "very-secret-password" not in events.text
            assert client.get(base + "/audit", headers=patient).status_code == 403

        with factory() as db:
            records = db.scalars(select(AdminAuditEvent)).all()
            assert len(records) == 6
    finally:
        app.dependency_overrides.clear()
