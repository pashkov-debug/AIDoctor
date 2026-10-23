"""UI-4B: валидация контрактов и поэлементного предпросмотра без БД."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.schemas.ai_review import DraftImport, ReviewAction
from app.services import ai_review as service
from fastapi import HTTPException
from pydantic import ValidationError


def medication(name: str, *, complete: bool = True) -> dict:
    return {
        "request_key": str(uuid4()),
        "kind": "medication",
        "name": name,
        "active_ingredient": "Синтетический компонент",
        "dosage_form": "учебная",
        "strength": "условная",
        "dose_value": "1",
        "dose_unit": "условная единица",
        "route": "учебный путь",
        "frequency_per_day": 1,
        "times_local": ["09:00"],
        "timezone": "Europe/Moscow",
        "start_date": "2026-10-23",
        "duration_days": 2 if complete else None,
        "indication": "Только тест",
        "rationale": "Вымышленный пример",
    }


def sample():
    a, b = str(uuid4()), str(uuid4())
    values = [
        {
            "id": a,
            "kind": "medication",
            "order": medication("А"),
            "alternative_group": "alternatives",
        },
        {
            "id": b,
            "kind": "medication",
            "order": medication("Б"),
            "alternative_group": "alternatives",
        },
    ]
    return DraftImport.model_validate({"origin": "synthetic_manual_test", "proposals": values})


def test_synthetic_schema_not_model_output():
    data = sample()
    assert len(data.proposals) == 2
    with pytest.raises(ValidationError):
        DraftImport.model_validate(
            {"origin": "openai", "proposals": [x.model_dump(mode="json") for x in data.proposals]}
        )
    with pytest.raises(ValidationError):
        DraftImport.model_validate(
            {
                "origin": "synthetic_manual_test",
                "proposals": [
                    data.proposals[0].model_dump(mode="json"),
                    data.proposals[0].model_dump(mode="json"),
                ],
            }
        )
    with pytest.raises(ValidationError):
        DraftImport.model_validate(
            {
                "origin": "synthetic_manual_test",
                "proposals": [
                    {
                        "id": str(uuid4()),
                        "kind": "medication",
                        "test_id": "DEMO_ANX_7",
                    }
                ],
            }
        )


def test_alternatives_cannot_be_approved_together(monkeypatch):
    proposals = sample()
    fake_case = SimpleNamespace(id=str(uuid4()), current_version=1, status="open")
    fake_request = SimpleNamespace(
        id=str(uuid4()), patient_id=str(uuid4()), doctor_id=str(uuid4()), context_sha256="x" * 64
    )
    monkeypatch.setattr(
        service,
        "_version",
        lambda *_: SimpleNamespace(
            proposals_json=[p.model_dump(mode="json") for p in proposals.proposals]
        ),
    )
    monkeypatch.setattr(service, "_fresh", lambda *_: None)
    monkeypatch.setattr(service, "_fingerprint", lambda *_: "f" * 64)
    choice = ReviewAction.model_validate(
        {
            "expected_version": 1,
            "selections": [{"proposal_id": str(p.id)} for p in proposals.proposals],
        }
    )
    with pytest.raises(HTTPException) as exc:
        service._prepare(None, fake_case, fake_request, choice)
    assert exc.value.status_code == 422
    assert "альтернатив" in exc.value.detail


def test_preview_includes_actual_technical_key_and_requires_reason(monkeypatch):
    proposals = sample()
    fake_case = SimpleNamespace(id=str(uuid4()), current_version=1, status="open")
    fake_request = SimpleNamespace(
        id=str(uuid4()), patient_id=str(uuid4()), doctor_id=str(uuid4()), context_sha256="x" * 64
    )
    monkeypatch.setattr(
        service,
        "_version",
        lambda *_: SimpleNamespace(
            proposals_json=[p.model_dump(mode="json") for p in proposals.proposals]
        ),
    )
    monkeypatch.setattr(service, "_fresh", lambda *_: None)
    monkeypatch.setattr(service, "_fingerprint", lambda *_: "f" * 64)
    first = proposals.proposals[0]
    edited = first.order.model_copy(update={"duration_days": 3})
    choice = ReviewAction.model_validate(
        {
            "expected_version": 1,
            "selections": [{"proposal_id": str(first.id), "order": edited.model_dump(mode="json")}],
        }
    )
    with pytest.raises(HTTPException) as exc:
        service._prepare(None, fake_case, fake_request, choice)
    assert exc.value.status_code == 422
    choice.edit_reason = "Врач скорректировал длительность"
    preview = service._prepare(None, fake_case, fake_request, choice)
    assert preview["changes"][0]["edited"] is True
    assert preview["changes"][0]["final"]["duration_days"] == 3
    assert preview["changes"][0]["original"]["duration_days"] == 2
    assert preview["changes"][0]["final"]["request_key"] != str(first.order.request_key)
    assert len(preview["preview_sha256"]) == 64


def test_incomplete_medication_blocked(monkeypatch):
    proposals = sample()
    first = proposals.proposals[0]
    first.order.duration_days = None
    fake_case = SimpleNamespace(id=str(uuid4()), current_version=1, status="open")
    fake_request = SimpleNamespace(
        id=str(uuid4()), patient_id=str(uuid4()), doctor_id=str(uuid4()), context_sha256="x" * 64
    )
    monkeypatch.setattr(
        service,
        "_version",
        lambda *_: SimpleNamespace(
            proposals_json=[p.model_dump(mode="json") for p in proposals.proposals]
        ),
    )
    with pytest.raises(HTTPException) as exc:
        service._prepare(
            None,
            fake_case,
            fake_request,
            ReviewAction.model_validate(
                {
                    "expected_version": 1,
                    "selections": [{"proposal_id": str(first.id)}],
                }
            ),
        )
    assert exc.value.status_code == 422
    assert "duration_days" in exc.value.detail
