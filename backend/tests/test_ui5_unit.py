"""UI-5: реальные препараты, невозможность превратить опасный учебный кейс в назначение."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.services.clinical_order import _check_ready
from fastapi import HTTPException

from backend.scripts.seed_ui5_clinical_scenarios import (
    ADDITIONAL_EVENTS,
    CANDIDATE_PREFIX,
    CRITICAL_VISITS,
    _require_synthetic,
    candidate_values,
    event_fact,
)


def test_real_drugs_and_structured_candidates_without_answer_leak() -> None:
    anchor = datetime(2026, 10, 23, tzinfo=UTC)
    interaction = candidate_values("1", anchor)
    dose_case = candidate_values("2", anchor)
    assert "сертралин" in interaction["active_ingredient"]
    assert interaction["dose_value"] == Decimal("50")
    assert dose_case["dose_value"] == Decimal("300")
    assert interaction["source_reference"].startswith(CANDIDATE_PREFIX)
    assert interaction["times_local"] == ["09:00"]
    assert "фенелзин" in ADDITIONAL_EVENTS["anxiety"][0][2]
    assert len(CRITICAL_VISITS) >= 3
    patient_payloads = (repr(ADDITIONAL_EVENTS) + repr(interaction) + repr(dose_case)).lower()
    for answer in ("200 мг", "серотониновый синдром", "противопоказ", "превышение доз"):
        assert answer not in patient_payloads


@pytest.mark.parametrize(
    "ref",
    [
        "synthetic:ui5:v1:candidate:1",
        "synthetic:ui5:v1:candidate:2",
    ],
)
def test_ui5_candidate_cannot_be_approved_even_with_all_fields(ref: str) -> None:
    with pytest.raises(HTTPException) as error:
        _check_ready(SimpleNamespace(source_reference=ref))
    assert error.value.status_code == 422


def test_unmarked_patient_rejected() -> None:
    with pytest.raises(ValueError, match="synthetic"):
        _require_synthetic(
            SimpleNamespace(
                demographics_json={},
                deleted_at=None,
            )
        )


def test_seeded_cases_span_more_than_month() -> None:
    offsets = [row[0] for row in CRITICAL_VISITS]
    assert max(offsets) - min(offsets) >= 30
    assert any("срочн" in event[2] for event in ADDITIONAL_EVENTS["critical"])


def test_reported_phenelzine_has_explicit_unverified_provenance() -> None:
    report = event_fact("anxiety", 1, "Со слов пациента")
    assert report["medication_report"]["active_ingredient"] == "фенелзин"
    assert report["medication_report"]["status"] == "reported_current"
    assert report["medication_report"]["clinician_verified"] is False
    assert report["medication_report"]["last_dose_date"] is None
