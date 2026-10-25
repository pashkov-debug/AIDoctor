"""Этап 1: контракты ручной записи и снятие искусственного AI-review-gate."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.core.access import require_active_doctor_patient
from app.schemas.clinical_entry import ManualHistoryCreate, ManualObservationCreate
from app.services import ai_review
from fastapi import HTTPException
from pydantic import ValidationError


def test_review_available_for_active_patient_independently_of_synthetic(monkeypatch):
    monkeypatch.setenv("AIDOCTOR_ALLOW_SYNTHETIC_AI_DRAFTS", "0")
    data = SimpleNamespace(deleted_at=None, demographics_json={})
    db = SimpleNamespace(get=lambda *_: data)
    assert ai_review.enabled_for_patient(db, str(uuid4())) is True
    data.demographics_json = {"synthetic": True}
    assert ai_review.enabled_for_patient(db, str(uuid4())) is True
    data.deleted_at = datetime.now(UTC)
    assert ai_review.enabled_for_patient(db, str(uuid4())) is False
    assert ai_review.enabled_for_patient(SimpleNamespace(get=lambda *_: None), "none") is False


@pytest.mark.parametrize("role", ["patient", "admin"])
def test_manual_entry_restricted_to_doctor(role):
    with pytest.raises(HTTPException) as exc:
        require_active_doctor_patient(None, SimpleNamespace(role=role), "patient-id")
    assert exc.value.status_code == 403


def test_history_and_observation_validate_input():
    history = ManualHistoryCreate.model_validate(
        {
            "category": "complaints",
            "fact": {"text": "Тревога и нарушение сна"},
            "occurred_at": "2026-08-03T09:00:00+03:00",
        }
    )
    assert history.occurred_at.utcoffset().total_seconds() == 10800
    observation = ManualObservationCreate.model_validate(
        {
            "code_system": "local",
            "code": "GAD-7",
            "value": {"score": 17, "maximum": 21},
        }
    )
    assert observation.value["score"] == 17
    for model, data in (
        (ManualHistoryCreate, {"category": "symptom", "fact": {}, "unknown": "x"}),
        (ManualHistoryCreate, {"category": "symptom", "fact": {}}),
        (
            ManualObservationCreate,
            {"code": "GAD-7", "value": {"score": 5}, "observed_at": "2026-08-03T09:00:00"},
        ),
        (ManualObservationCreate, {"code": "x", "value": {"text": "x" * 20000}}),
    ):
        with pytest.raises(ValidationError):
            model.model_validate(data)
