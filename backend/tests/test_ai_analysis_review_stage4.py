"""Этап 4: происхождение предложений и строгий врачебный предпросмотр."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.schemas.ai_review import (
    ClinicianOrderSupplement,
    Proposal,
    ReviewAction,
    Selection,
)
from app.schemas.clinical_entry import ManualHistoryCreate
from app.services import ai_review
from fastapi import HTTPException
from pydantic import ValidationError


def make_analysis(*, include_medicine_risk=True):
    analysis_id, patient_id, request_id = uuid4(), uuid4(), uuid4()
    payload = {
        "schema_version": "aidoctor_demo_analysis.v1",
        "request_id": str(request_id),
        "patient_id": str(patient_id),
        "context_sha256": "0" * 64,
        "orders_sha256": "1" * 64,
        "status": "draft_requires_review",
        "summary": "Сохранённый учебный результат внешнего агента для врачебной проверки.",
        "suggested_examinations": [
            {
                "name": "Консультация специалиста",
                "rationale": "Оценить клиническую необходимость обследования на очном приёме",
            }
        ],
        "hypotheses": [
            {
                "title": "Генерализованное тревожное расстройство",
                "rationale": "Тревожные симптомы продолжительностью более шести месяцев",
                "confidence": "uncertain",
            }
        ],
        "medication_risks": [
            {
                "medication": "Препарат из документа",
                "risk": "Требуется проверка возможной сонливости и взаимодействий",
                "severity": "unknown",
            }
        ]
        if include_medicine_risk
        else [],
    }
    return SimpleNamespace(
        id=str(analysis_id),
        request_id=str(request_id),
        patient_id=str(patient_id),
        payload_json=payload,
        payload_sha256="c" * 64,
    )


def test_ai_v1_maps_only_supported_proposals():
    row = make_analysis()
    proposals = ai_review._proposals_from_analysis(row)
    assert len(proposals) == 3
    assert [p.kind for p in proposals] == ["examination", "history_event", "history_event"]
    assert not any(p.kind == "medication" for p in proposals)
    assert proposals[0].order.source_reference.startswith("AI-анализ")
    assert proposals[1].history.fact["classification"].startswith("предложение AI")
    assert proposals[2].history.category == "ai_medication_risk"
    assert all(p.evidence_status == "unverified_ai" for p in proposals)


def test_mapping_is_stable_for_retry():
    row = make_analysis()
    first = [p.model_dump(mode="json") for p in ai_review._proposals_from_analysis(row)]
    second = [p.model_dump(mode="json") for p in ai_review._proposals_from_analysis(row)]
    assert first == second
    assert len({p["id"] for p in first}) == len(first)


def test_proposal_rejects_cross_kind_fields():
    with pytest.raises(ValidationError):
        Proposal(
            id=uuid4(),
            kind="history_event",
            history=ManualHistoryCreate(category="anxiety", fact={"note": "Описание"}),
            test_id="DEMO_ANX_7",
        )


def test_clinician_drug_must_have_full_order():
    with pytest.raises(ValidationError):
        ClinicianOrderSupplement(
            expected_version=1,
            order={
                "request_key": str(uuid4()),
                "kind": "medication",
                "name": "Тестовый препарат",
                "dose_value": -1,
            },
        )


def test_ai_hypothesis_requires_physician_reason_for_edit(monkeypatch):
    proposal = ai_review._proposals_from_analysis(make_analysis())[1]
    case_id, request_id, patient_id = str(uuid4()), str(uuid4()), str(uuid4())
    case = SimpleNamespace(
        id=case_id,
        current_version=1,
        status="open",
    )
    request = SimpleNamespace(
        id=request_id,
        patient_id=patient_id,
        doctor_id=str(uuid4()),
        context_sha256="f" * 64,
    )
    version = SimpleNamespace(
        origin="site_builder_analysis_v1", proposals_json=[proposal.model_dump(mode="json")]
    )
    monkeypatch.setattr(ai_review, "_version", lambda db, case_: version)
    monkeypatch.setattr(ai_review, "_fresh", lambda db, request_: None)
    monkeypatch.setattr(ai_review, "_fingerprint", lambda db, pid: "z" * 64)

    changed = proposal.history.model_copy(deep=True)
    changed.fact["rationale"] = "Решение врача уточнено"
    action = ReviewAction(
        expected_version=1,
        selections=[
            Selection(proposal_id=proposal.id, history=changed),
        ],
    )
    with pytest.raises(HTTPException) as exc:
        ai_review._prepare(None, case, request, action)
    assert exc.value.status_code == 422
    assert "причину" in exc.value.detail

    action = ReviewAction(
        expected_version=1,
        selections=[
            Selection(proposal_id=proposal.id, history=changed),
        ],
        edit_reason="Уточнение врача",
    )
    result = ai_review._prepare(None, case, request, action)
    assert result["changes"][0]["edited"] is True
    assert result["not_selected"] == []
    assert len(result["preview_sha256"]) == 64


def test_cannot_remove_ai_uncertainty_label(monkeypatch):
    proposal = ai_review._proposals_from_analysis(make_analysis())[1]
    case = SimpleNamespace(id=str(uuid4()), current_version=1, status="open")
    request = SimpleNamespace(id=str(uuid4()), patient_id=str(uuid4()), doctor_id=str(uuid4()))
    version = SimpleNamespace(
        origin="site_builder_analysis_v1", proposals_json=[proposal.model_dump(mode="json")]
    )
    monkeypatch.setattr(ai_review, "_version", lambda db, case_: version)
    manipulated = proposal.history.model_copy(deep=True)
    manipulated.fact["classification"] = "подтверждённый диагноз"
    with pytest.raises(HTTPException) as exc:
        ai_review._prepare(
            None,
            case,
            request,
            ReviewAction(
                expected_version=1,
                edit_reason="Подмена происхождения",
                selections=[Selection(proposal_id=proposal.id, history=manipulated)],
            ),
        )
    assert exc.value.status_code == 422
