"""Изолированные проверки контракта обратного AI-канала без PostgreSQL."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from app.schemas.ai_demo_bridge import DemoAnalysisSubmit
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]


def sample() -> dict:
    return {
        "schema_version": "aidoctor_demo_analysis.v1",
        "request_id": str(uuid4()),
        "patient_id": str(uuid4()),
        "context_sha256": "a" * 64,
        "orders_sha256": "b" * 64,
        "status": "draft_requires_review",
        "summary": "Учебный синтетический ответ, который врач обязан проверить самостоятельно.",
        "hypotheses": [
            {
                "title": "Учебная гипотеза",
                "rationale": "Требуется дальнейшее уточнение клинических сведений",
                "confidence": "uncertain",
            }
        ],
        "medication_risks": [],
        "missing_information": ["Уточнить лекарственную историю"],
        "suggested_examinations": [],
        "sources": [],
        "limitations": [],
    }


def test_accepts_versioned_demo_payload() -> None:
    parsed = DemoAnalysisSubmit.model_validate(sample())
    assert parsed.schema_version == "aidoctor_demo_analysis.v1"
    assert parsed.status == "draft_requires_review"


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("schema_version", "ai_review.v1"),
        ("status", "approved"),
        ("context_sha256", "x" * 64),
        ("orders_sha256", "a" * 63),
        ("request_id", "arbitrary"),
        ("summary", "short"),
    ],
)
def test_rejects_incompatible_input(field: str, invalid: str) -> None:
    payload = sample()
    payload[field] = invalid
    with pytest.raises(ValidationError):
        DemoAnalysisSubmit.model_validate(payload)


def test_rejects_unexpected_medical_actions() -> None:
    payload = sample()
    payload["approved_orders"] = [{"name": "не должно приниматься"}]
    with pytest.raises(ValidationError):
        DemoAnalysisSubmit.model_validate(payload)


def test_rejects_oversized_list_and_source_url() -> None:
    payload = sample()
    payload["missing_information"] = ["A" * 501]
    with pytest.raises(ValidationError):
        DemoAnalysisSubmit.model_validate(payload)
    payload = sample()
    payload["sources"] = [
        {"title": "Источник", "url": "file:///etc/passwd", "relevance": "Неизвестно"}
    ]
    with pytest.raises(ValidationError):
        DemoAnalysisSubmit.model_validate(payload)


def test_canonical_payload_checksum_is_stable() -> None:
    data = DemoAnalysisSubmit.model_validate(sample()).model_dump(mode="json")
    reversed_data = dict(reversed(list(data.items())))

    def digest(value: dict) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

    assert digest(data) == digest(reversed_data)


def test_bridge_requires_explicit_authorization_and_synthetic_patient() -> None:
    text = (ROOT / "backend/app/api/routes/ai_demo_bridge.py").read_text(encoding="utf-8")
    for safeguard in (
        'settings.app_env == "test"',
        "AIDOCTOR_DEMO_CALLBACK_ENABLED",
        "AIDOCTOR_SITE_BRIDGE_TOKEN",
        'doctor.username != "doctor_ui1"',
        'patient.demographics_json.get("synthetic") is not True',
        "DoctorPatient.doctor_id == row.doctor_id",
        "get_agent_context(",
        "_fresh(db, row)",
        "hmac.compare_digest",
    ):
        assert safeguard in text


def test_migration_adds_only_separate_demo_table() -> None:
    migration = (
        ROOT / "backend/alembic/versions/ai_bridge_v1_20261024_demo_analysis.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision = "ui6a_20261023"' in migration
    assert '"ai_demo_analyses"' in migration
    assert 'op.drop_table("ai_demo_analyses")' in migration
    assert "clinical_orders" not in migration
