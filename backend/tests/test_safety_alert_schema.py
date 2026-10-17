"""Локальные проверки границ входного контракта, без PostgreSQL."""

import pytest
from app.schemas.safety_alert import SafetyAlertCreate
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("reason", "priority"),
    [
        ("clinician_review", "standard"),
        ("care_coordination", "urgent"),
        ("urgent_attention", "urgent"),
    ],
)
def test_valid_codes(reason, priority):
    assert SafetyAlertCreate(reason_code=reason, priority=priority).reason_code == reason


@pytest.mark.parametrize(
    ("reason", "priority"),
    [
        ("medical_diagnosis", "urgent"),
        ("urgent_attention", "emergency_autodispatch"),
        ("", "standard"),
    ],
)
def test_unknown_codes_rejected(reason, priority):
    with pytest.raises(ValidationError):
        SafetyAlertCreate(reason_code=reason, priority=priority)
