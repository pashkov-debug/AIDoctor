"""Входной контракт UI-4B: только явно помеченный синтетический ручной пример."""

from typing import Literal
from uuid import UUID

from app.schemas.clinical_order import OrderDraftCreate
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    kind: Literal["medication", "examination", "demo_test"]
    order: OrderDraftCreate | None = None
    test_id: Literal["DEMO_ANX_7", "DEMO_DEP_9"] | None = None
    alternative_group: str | None = Field(default=None, max_length=60)
    evidence_status: Literal["unverified_demo"] = "unverified_demo"

    @model_validator(mode="after")
    def match_kind(self):
        if self.kind == "demo_test":
            if self.order is not None or self.test_id is None:
                raise ValueError("Для теста нужен test_id без order")
        elif self.order is None or self.order.kind != self.kind or self.test_id is not None:
            raise ValueError("Тип предложения и его поля не совпадают")
        return self


class DraftImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int | None = Field(default=None, ge=1)
    origin: Literal["synthetic_manual_test"]
    proposals: list[Proposal] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({p.id for p in self.proposals}) != len(self.proposals):
            raise ValueError("ID предложений должны быть уникальны")
        return self


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: UUID
    order: OrderDraftCreate | None = None
    test_id: Literal["DEMO_ANX_7", "DEMO_DEP_9"] | None = None


class ReviewAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    selections: list[Selection] = Field(min_length=1, max_length=12)
    edit_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def no_duplicates(self):
        if len({x.proposal_id for x in self.selections}) != len(self.selections):
            raise ValueError("Выбранные ID не должны повторяться")
        return self


class ReviewCommit(ReviewAction):
    preview_sha256: str = Field(min_length=64, max_length=64)
    confirm_patient_visibility: Literal[True]
    confirm_clinical_review: Literal[True]


class RejectDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


class DraftRead(BaseModel):
    schema_version: Literal["ai_review.v1"] = "ai_review.v1"
    case_id: str
    request_id: str
    status: str
    version: int
    origin: Literal["synthetic_manual_test"] = "synthetic_manual_test"
    proposals: list[Proposal]
    versions_available: list[int]
    approved_result: dict | None = None
