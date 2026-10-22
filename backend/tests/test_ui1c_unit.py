"""Контракты UI-1C, не требующие SQL-соединения."""

from pathlib import Path

import pytest
from app.main import app
from app.schemas.admin import CreateAccount, CreateSyntheticPatient
from fastapi.testclient import TestClient
from pydantic import ValidationError


def test_admin_create_account_validation() -> None:
    account = CreateAccount(username="doctor_ui1", password="secure-passphrase", role="doctor")
    assert account.role == "doctor"
    with pytest.raises(ValidationError):
        CreateAccount(username="hacker", password="secure-passphrase", role="admin")
    with pytest.raises(ValidationError):
        CreateAccount(username="doctor", password="123", role="doctor")
    with pytest.raises(ValidationError):
        CreateAccount(username="doctor name", password="secure-passphrase", role="doctor")
    with pytest.raises(ValidationError):
        CreateAccount(username="demo", password="secure-passphrase", role="doctor", admin=True)
    assert CreateSyntheticPatient(alias="  Синтетический  ").alias == "Синтетический"
    with pytest.raises(ValidationError):
        CreateSyntheticPatient(alias="   ")


def test_admin_public_shell_private_api_and_no_browser_token_storage() -> None:
    with TestClient(app) as client:
        html = client.get("/app")
        assert html.status_code == 200
        assert 'id="admin-view"' in html.text
        assert 'id="admin-user-form"' in html.text
        assert 'id="admin-bind-form"' in html.text
        assert 'id="admin-audit"' in html.text
        assert "no-store" in html.headers["cache-control"]
        assert client.get("/admin/users").status_code == 404
        for route in ("/admin/users", "/admin/patients", "/admin/links", "/admin/audit"):
            assert client.get(f"/api/v1{route}").status_code == 401
        assert client.post("/api/v1/admin/users", json={
            "username": "demo", "password": "secure-passphrase", "role": "doctor"
        }).status_code == 401
        assert client.delete("/api/v1/admin/links/something").status_code == 401
    script = (
        Path(__file__).resolve().parents[1] / "app" / "web" / "assets" / "app.js"
    ).read_text(encoding="utf-8")
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "innerHTML" not in script
    assert 'api("/admin/users")' in script
    assert 'api("/admin/patients")' in script
    assert 'api("/admin/links")' in script
    assert 'api("/admin/audit")' in script
