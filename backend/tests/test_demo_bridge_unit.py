"""Негативные сценарии публичного синтетического Bridge без PostgreSQL."""

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.services.context_builder import ClinicalContext, ContextFact
from demo_bridge import contract
from demo_bridge.config import validated_demo_url
from demo_bridge.server import create_app


def _fake_context() -> ClinicalContext:
    items = [
        ContextFact(
            kind=kind,
            record_id=identifier,
            at=datetime(2026, 10, 19, tzinfo=UTC),
            source_ref=f"synthetic:{kind}:{identifier}",
            payload=(
                {"details": {"synthetic": True}}
                if kind == "encounter"
                else {"fact": {"synthetic": True}}
                if kind == "history_event"
                else {"value": {"synthetic": True}}
            ),
        )
        for kind, identifier in sorted(contract.ALLOWED_FACTS)
    ]
    canonical = {
        "schema_version": "1.0",
        "patient_id": contract.PATIENT_ID,
        "items": [item.model_dump(mode="json", exclude_none=False) for item in items],
        "truncated_sources": [],
        "excluded_attachments_count": 0,
    }
    return ClinicalContext(
        **canonical,
        generated_at=datetime(2026, 10, 20, tzinfo=UTC),
        content_sha256=contract.sha256_data(canonical),
    )


class _DemoSession:
    patient = SimpleNamespace(
        alias=contract.PUBLIC_ID,
        deleted_at=None,
        demographics_json={"synthetic": True, "sex": "female", "age_years": 35},
    )
    count = 1

    def scalar(self, _statement):
        return self.count

    def get(self, _model, identity):
        return self.patient if identity == contract.PATIENT_ID else None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_config_only_local_demo_database():
    ok = validated_demo_url(
        "postgresql+psycopg://aidoctor:secret@127.0.0.1:5432/aidoctor_demo"
    )
    assert ok.database == "aidoctor_demo"
    invalid = [
        "",
        "sqlite:///aidoctor_demo",
        "postgresql+psycopg://aidoctor:secret@127.0.0.1/aidoctor",
        "postgresql+psycopg://aidoctor:secret@localhost/aidoctor_test",
        "postgresql+psycopg://aidoctor:secret@db.internal/aidoctor_demo",
        "postgresql+psycopg://aidoctor:secret@127.0.0.1:6543/aidoctor_demo",
        "postgresql+psycopg://postgres:secret@127.0.0.1/aidoctor_demo",
        "postgresql+psycopg://aidoctor:secret@127.0.0.1/aidoctor_demo?sslmode=disable",
        "postgresql+psycopg://aidoctor@localhost/aidoctor_demo",
    ]
    for url in invalid:
        with pytest.raises(ValueError):
            validated_demo_url(url)


def test_hash_canonicalization_unicode_and_field_order():
    a = {"а": 1, "b": {"x": True}, "c": [1, 2]}
    b = {"c": [1, 2], "b": {"x": True}, "а": 1}
    assert contract.sha256_data(a) == contract.sha256_data(b)
    assert contract.sha256_data(a) == hashlib.sha256(
        contract.canonical_bytes(a)
    ).hexdigest()
    assert contract.sha256_data({"a": None}) != contract.sha256_data({})


def test_http_contract_and_no_mutations(monkeypatch):
    session = _DemoSession()
    monkeypatch.setattr(contract, "ContextBuilder", lambda _session: SimpleNamespace(
        build=lambda _id: _fake_context()
    ))
    client = TestClient(create_app(session_factory=lambda: session))
    for endpoint in ("/demo/v1/patient", "/demo/v1/context"):
        response = client.get(endpoint)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        body = response.json()
        assert body["synthetic"] is True
        assert body["clinical_processing_allowed"] is False
        assert body["content_sha256"] == contract.sha256_data(body["data"])
    assert client.get("/demo/v1/context").json()["data"]["clinical_context"][
        "content_sha256"
    ] == _fake_context().content_sha256
    assert client.post("/demo/v1/context").status_code == 405
    assert client.get("/api/v1/patients").status_code == 404
    assert client.get("/health").json()["status"] == "ok"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("count", 2),
        ("alias", "real-person"),
        ("demographics_json", {"synthetic": False, "sex": "female", "age_years": 35}),
    ],
)
def test_bad_seed_denied(monkeypatch, field, value):
    monkeypatch.setattr(contract, "ContextBuilder", lambda _session: SimpleNamespace(
        build=lambda _id: _fake_context()
    ))
    session = _DemoSession()
    if field == "count":
        session.count = value
    else:
        setattr(session.patient, field, value)
    client = TestClient(create_app(session_factory=lambda: session))
    response = client.get("/demo/v1/context")
    assert response.status_code == 503
    assert "secret" not in response.text


def test_tampered_clinical_hash_denied(monkeypatch):
    fake = _fake_context()
    fake.content_sha256 = "0" * 64
    monkeypatch.setattr(contract, "ContextBuilder", lambda _session: SimpleNamespace(
        build=lambda _id: fake
    ))
    client = TestClient(create_app(session_factory=_DemoSession))
    assert client.get("/demo/v1/context").status_code == 503


def test_unavailable_database_does_not_leak_exception():
    class Broken:
        def __enter__(self):
            raise RuntimeError("password=SUPER_SECRET")

        def __exit__(self, *_args):
            return False

    client = TestClient(create_app(session_factory=Broken))
    response = client.get("/demo/v1/context")
    assert response.status_code == 503
    assert "SUPER_SECRET" not in response.text
