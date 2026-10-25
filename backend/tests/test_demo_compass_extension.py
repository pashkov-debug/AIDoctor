"""Контракт расширения MCP и проверка ошибочного учебного назначения."""

from decimal import Decimal
from uuid import uuid4

import pytest
from app.clinical.medication_safety import check_order_regimen
from app.schemas.ai_review import Proposal
from app.schemas.ai_structured_proposals import StructuredProposalSubmit
from app.schemas.clinical_order import OrderDraftCreate
from pydantic import ValidationError


def _payload(order_dose: Decimal = Decimal("20")) -> dict:
    order = OrderDraftCreate(
        request_key=uuid4(),
        kind="medication",
        name="Авиандр",
        active_ingredient="маритупирдин",
        dosage_form="таблетки, покрытые пленочной оболочкой",
        strength="20 мг",
        dose_value=order_dose,
        dose_unit="мг",
        route="внутрь",
        frequency_per_day=2,
        times_local=["09:00", "21:00"],
        timezone="Europe/Moscow",
        indication="ГТР (учебный пример)",
        rationale="Клинический разбор врачом",
        start_date="2026-08-03",
        duration_days=28,
    )
    proposal = Proposal(
        id=uuid4(),
        kind="medication",
        order=order,
        evidence_status="unverified_ai",
    )
    return {
        "schema_version": "aidoctor_structured_proposals.v1",
        "request_id": uuid4(),
        "patient_id": uuid4(),
        "context_sha256": "a" * 64,
        "orders_sha256": "b" * 64,
        "analysis_payload_sha256": "c" * 64,
        "proposals": [proposal.model_dump(mode="json")],
    }


def test_structured_proposal_accepts_valid_medication():
    value = StructuredProposalSubmit.model_validate(_payload())
    assert value.proposals[0].order.dose_value == Decimal("20")


def test_structured_proposals_forbid_clinician_impersonation():
    payload = _payload()
    payload["proposals"][0]["evidence_status"] = "clinician_added"
    with pytest.raises(ValidationError):
        StructuredProposalSubmit.model_validate(payload)


def test_structured_proposals_forbid_duplicate_ids():
    payload = _payload()
    payload["proposals"].append(payload["proposals"][0])
    with pytest.raises(ValidationError):
        StructuredProposalSubmit.model_validate(payload)


def test_registered_regimen_no_warning():
    assert (
        check_order_regimen(
            name="Авиандр",
            active_ingredient="маритупирдин",
            dose_value=20,
            dose_unit="мг",
            frequency_per_day=2,
        )
        is None
    )


def test_incorrect_dose_warns_without_claiming_certain_injury():
    result = check_order_regimen(
        name="Авиандр",
        active_ingredient="маритупирдин",
        dose_value=40,
        dose_unit="мг",
        frequency_per_day=2,
    )
    assert result is not None and result["severity"] == "high"
    assert "80 мг/сут" in result["message"]
    assert "не предсказываются" in result["basis"]


def test_different_drug_ignored():
    assert (
        check_order_regimen(
            name="Другой препарат",
            active_ingredient="другое вещество",
            dose_value=40,
            dose_unit="мг",
            frequency_per_day=2,
        )
        is None
    )
