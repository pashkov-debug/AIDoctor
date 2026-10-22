"""Контракт UI-1B без подключения к PostgreSQL."""

from pathlib import Path

from app.main import app
from app.schemas.patient_portal import PatientPortalRead
from fastapi.testclient import TestClient


def test_portal_projection_does_not_accept_internal_fields() -> None:
    schema = PatientPortalRead.model_json_schema()
    fields = set(schema["properties"])
    assert fields == {"schema_version", "patient_id", "alias", "created_at"}
    assert "demographics" not in fields
    assert "draft" not in fields
    assert "user_id" not in fields
    assert "password_hash" not in fields


def test_patient_portal_public_shell_protected_api() -> None:
    with TestClient(app) as client:
        response = client.get("/app")
        assert response.status_code == 200
        assert "no-store" in response.headers["cache-control"]
        assert 'id="patient-view"' in response.text
        assert 'id="patient-details"' in response.text
        assert 'id="admin-view"' in response.text
        assert "Назначения появятся только после" in response.text
        assert client.get("/api/v1/patients/me/portal").status_code == 401
        assert client.get("/app/assets/app.js").status_code == 200

    script = (
        Path(__file__).resolve().parents[1] / "app" / "web" / "assets" / "app.js"
    ).read_text(encoding="utf-8")
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "innerHTML" not in script
    assert 'api("/patients/me/portal")' in script
    assert '["doctor", "patient", "admin"]' in script
