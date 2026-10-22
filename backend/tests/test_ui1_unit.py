"""Быстрые контракты UI-1, не требуют работающего PostgreSQL."""

from pathlib import Path

import pytest
from app.main import app
from app.schemas.doctor_settings import ClinicalFields, ProfileFields
from app.services.doctor_settings import read_doctor_context, read_settings
from fastapi.testclient import TestClient
from pydantic import ValidationError


class EmptySession:
    def get(self, model, key):
        return None


def test_ui1_rki_semantics_and_doctor_context_minimal() -> None:
    session = EmptySession()
    settings = read_settings(session, "doctor-id")
    assert settings.version == 0
    assert settings.clinical.rki_mode == "disabled"
    context = read_doctor_context(session, "doctor-id").model_dump()
    assert context["schema_version"] == "doctor_context.v1"
    assert context["profile_version"] == 0
    assert context["rki"]["scope"] == "russian_clinical_guidelines_approved_by_minzdrav"
    assert context["rki"]["source_verification"] == "required"
    assert "patient_id" not in context
    assert "contact_email" not in context


def test_ui1_strict_fields() -> None:
    assert ProfileFields(full_name="  Тестовый врач  ").full_name == "Тестовый врач"
    assert ClinicalFields(clinical_specialty="   ").clinical_specialty is None
    with pytest.raises(ValidationError):
        ClinicalFields(rki_mode="mandatory")
    with pytest.raises(ValidationError):
        ProfileFields(contact_email="not an email")
    with pytest.raises(ValidationError):
        ClinicalFields(practice_country="X" * 121)
    with pytest.raises(ValidationError):
        ProfileFields.model_validate({"unknown": "something"})


def test_ui1_web_public_but_no_private_data() -> None:
    with TestClient(app) as client:
        response = client.get("/app")
        assert response.status_code == 200
        assert "no-store" in response.headers["cache-control"]
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert 'id="workspace"' in response.text
        assert "Доступны кабинеты врача, пациента и администратора" in response.text
        assert (
            "Российские клинические рекомендации, утверждённые Минздравом России"
            in response.text
        )
        assert 'id="clinical-rki"' in response.text
        assert client.get("/app/assets/app.js").status_code == 200
        assert client.get("/").status_code == 200
        assert client.get("/api/v1/doctors/me/settings").status_code == 401
        assert client.get("/api/v1/doctors/me/doctor-context").status_code == 401
    script = (
        Path(__file__).resolve().parents[1] / "app" / "web" / "assets" / "app.js"
    ).read_text(encoding="utf-8")
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "innerHTML" not in script
    assert '["doctor", "patient", "admin"]' in script
    assert 'api("/admin/users")' in script
