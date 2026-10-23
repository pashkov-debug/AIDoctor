"""UI-6A: содержимое снимка лекарственных проектов и версионирование."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.schemas.ai_agent_context import OrdersReviewSnapshot
from app.services.ai_agent_context import (
    _serialise_order,
    build_orders_review,
    review_hash,
)
from fastapi import HTTPException
from pydantic import ValidationError


def _order(**overrides):
    data = dict(
        id="1",
        version=2,
        status="draft",
        kind="medication",
        name="Сертралин",
        active_ingredient="сертралин",
        dosage_form="таблетки",
        strength="100 мг",
        dose_value=Decimal("300.00"),
        dose_unit="мг",
        route="внутрь",
        frequency_per_day=1,
        times_local=["09:00"],
        timezone="Europe/Moscow",
        start_date=date(2026, 10, 23),
        duration_days=30,
        administration_notes=None,
        examination_details=None,
        indication="Синтетический сценарий",
        contraindications=None,
        rationale="Только учебный черновик",
        source_reference="synthetic:ui5:v1:candidate:2",
    )
    data.update(overrides)
    return SimpleNamespace(**data)


def test_draft_remains_explicitly_not_approved():
    draft = _serialise_order(_order())
    assert draft["dose_value"] == "300.00"
    assert draft["start_date"] == "2026-10-23"
    assert draft["status"] == "draft"
    assert "verdict" not in draft
    assert "correct_dose" not in draft

    snapshot = OrdersReviewSnapshot(approved_orders=[], proposed_orders_for_review=[draft])
    assert snapshot.draft_orders_are_not_treatment is True
    assert snapshot.clinical_safety_validated is False
    with pytest.raises(ValidationError):
        OrdersReviewSnapshot(
            approved_orders=[],
            proposed_orders_for_review=[draft],
            clinical_safety_validated=True,
        )


def test_fingerprint_is_order_independent_for_object_keys():
    one = {"approved_orders": [], "proposed_orders_for_review": [{"dose": "50"}]}
    two = {"proposed_orders_for_review": [{"dose": "50"}], "approved_orders": []}
    assert review_hash(one) == review_hash(two)
    two["proposed_orders_for_review"][0]["dose"] = "300"
    assert review_hash(one) != review_hash(two)


def test_refuse_truncated_list_without_partial_context(monkeypatch):
    from app.services import ai_agent_context as mod

    class FakeScalar:
        def all(self):
            return [_order(id=str(i)) for i in range(3)]

    class FakeSession:
        def scalars(self, statement):
            return FakeScalar()

    monkeypatch.setattr(mod, "MAX_REVIEW_ORDERS", 2)
    with pytest.raises(HTTPException) as error:
        build_orders_review(FakeSession(), "patient")
    assert error.value.status_code == 409


def test_approved_and_draft_are_disjoint(monkeypatch):

    class FakeScalar:
        def all(self):
            return [_order(id="1", status="draft"), _order(id="2", status="approved", version=4)]

    class FakeSession:
        def scalars(self, statement):
            return FakeScalar()

    result = build_orders_review(FakeSession(), "patient")
    assert len(result["approved_orders"]) == 1
    assert len(result["proposed_orders_for_review"]) == 1
    assert result["approved_orders"][0]["id"] == "2"
    assert result["proposed_orders_for_review"][0]["id"] == "1"
