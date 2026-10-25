"""Структурированные предложения: источник AI либо ручной учебный сценарий."""

from typing import Literal
from uuid import UUID

from app.schemas.clinical_entry import ManualHistoryCreate, ManualObservationCreate
from app.schemas.clinical_order import OrderDraftCreate
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    kind: Literal["medication", "examination", "demo_test", "history_event", "observation"]
    order: OrderDraftCreate | None = None
    test_id: Literal["DEMO_ANX_7", "DEMO_DEP_9"] | None = None
    history: ManualHistoryCreate | None = None
    observation: ManualObservationCreate | None = None
    source_locator: str | None = Field(default=None, max_length=180)
    alternative_group: str | None = Field(default=None, max_length=60)
    evidence_status: Literal["unverified_demo", "unverified_ai", "clinician_added"] = (
        "unverified_demo"
    )

    @model_validator(mode="after")
    def match_kind(self):
        populated = {
            "order": self.order is not None,
            "test": self.test_id is not None,
            "history": self.history is not None,
            "observation": self.observation is not None,
        }
        expected = {
            "medication": "order",
            "examination": "order",
            "demo_test": "test",
            "history_event": "history",
            "observation": "observation",
        }[self.kind]
        if not populated[expected] or sum(populated.values()) != 1:
            raise ValueError("Тип предложения и заполненные поля не совпадают")
        if self.order is not None and self.order.kind != self.kind:
            raise ValueError("Вид назначения не совпадает с видом предложения")
        return self


class DraftImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int | None = Field(default=None, ge=1)
    origin: Literal["synthetic_manual_test"]
    proposals: list[Proposal] = Field(min_length=1, max_length=36)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({p.id for p in self.proposals}) != len(self.proposals):
            raise ValueError("ID предложений должны быть уникальны")
        return self


class ClinicianOrderSupplement(BaseModel):
    """Врачебное предложение, не выдаётся за содержимое AI-ответа."""

    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    order: OrderDraftCreate


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: UUID
    order: OrderDraftCreate | None = None
    history: ManualHistoryCreate | None = None
    observation: ManualObservationCreate | None = None
    test_id: Literal["DEMO_ANX_7", "DEMO_DEP_9"] | None = None


class ReviewAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    selections: list[Selection] = Field(min_length=1, max_length=36)
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
    origin: Literal[
        "synthetic_manual_test", "site_builder_analysis_v1", "site_builder_structured_v1"
    ] = "synthetic_manual_test"
    proposals: list[Proposal]
    versions_available: list[int]
    approved_result: dict | None = None
