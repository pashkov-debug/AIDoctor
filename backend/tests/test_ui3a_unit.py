"""UI-3A: валидация структуры, отсутствие неявного времени и дозировки."""

from uuid import uuid4

import pytest
from app.schemas.clinical_order import OrderApprove, OrderDraftCreate, OrderUpdate
from pydantic import ValidationError

KEY = str(uuid4())


def test_incomplete_medication_is_valid_draft_without_invented_dose():
    data = OrderDraftCreate(kind="medication", name="Учебный препарат", request_key=KEY)
    assert data.dose_value is None
    assert data.times_local is None
    assert data.duration_days is None


def test_times_and_units_validation():
    base = dict(kind="medication", name="Учебный препарат", request_key=KEY)
    assert OrderDraftCreate(**base, times_local=["20:00", "08:00"]).times_local == [
        "08:00",
        "20:00",
    ]
    for bad in (["8:00"], ["25:00"], ["09:00", "09:00"], ["09:00:00"]):
        with pytest.raises(ValidationError):
            OrderDraftCreate(**base, times_local=bad)
    with pytest.raises(ValidationError):
        OrderDraftCreate(**base, dose_value="0")
    with pytest.raises(ValidationError):
        OrderDraftCreate(**base, dose_value="-2")
    with pytest.raises(ValidationError):
        OrderDraftCreate(**base, frequency_per_day=13)


def test_examination_cannot_have_medication_fields():
    with pytest.raises(ValidationError):
        OrderDraftCreate(
            kind="examination", name="Учебное обследование", request_key=KEY, dose_unit="мг"
        )
    with pytest.raises(ValidationError):
        OrderDraftCreate(kind="medication", name="X", request_key=KEY, examination_details="тест")


def test_explicit_approval_and_contract_versions():
    with pytest.raises(ValidationError):
        OrderApprove(
            expected_version=1, confirm_patient_visibility=False, confirm_clinical_review=True
        )
    with pytest.raises(ValidationError):
        OrderApprove(
            expected_version=1, confirm_patient_visibility=True, confirm_clinical_review=False
        )
    with pytest.raises(ValidationError):
        OrderUpdate(
            expected_version=0, data={"kind": "examination", "name": "X", "request_key": KEY}
        )


def test_extra_fields_and_invalid_timezone_rejected():
    with pytest.raises(ValidationError):
        OrderDraftCreate(kind="examination", name="X", request_key=KEY, ai_approved=True)
    with pytest.raises(ValidationError):
        OrderDraftCreate(
            kind="medication", name="X", request_key=KEY, timezone="Some/DefinitelyInvalidLocation"
        )
