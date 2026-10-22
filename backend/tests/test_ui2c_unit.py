"""UI-2C: контракт публикации и запрет неявного согласия."""

import pytest
from app.schemas.clinical_publication import PublishRequest, RevokeRequest
from pydantic import ValidationError


def test_explicit_publish_confirmation_and_validation():
    data = PublishRequest(
        expected_version=1,
        patient_text="Согласованное сообщение пациенту",
        confirm_patient_visibility=True,
    )
    assert data.patient_text == "Согласованное сообщение пациенту"
    for payload in (
        {"expected_version": 1, "patient_text": "Текст"},
        {"expected_version": 1, "patient_text": "Текст", "confirm_patient_visibility": False},
        {"expected_version": 0, "patient_text": "Текст", "confirm_patient_visibility": True},
        {"expected_version": 1, "patient_text": "", "confirm_patient_visibility": True},
        {
            "expected_version": 1,
            "patient_text": "Текст",
            "confirm_patient_visibility": True,
            "is_admin": True,
        },
    ):
        with pytest.raises(ValidationError):
            PublishRequest.model_validate(payload)


def test_revoke_requires_reason_and_version():
    with pytest.raises(ValidationError):
        RevokeRequest(expected_version=0, reason="Причина")
    with pytest.raises(ValidationError):
        RevokeRequest(expected_version=2, reason="x")
