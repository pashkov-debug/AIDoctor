"""Дополнительные клинические предложения от существующего Site Builder/MCP.

Не заменяет контракт aidoctor_demo_analysis.v1 и не утверждает лечение.
"""

from typing import Literal
from uuid import UUID

from app.schemas.ai_review import Proposal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StructuredProposalSubmit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["aidoctor_structured_proposals.v1"]
    request_id: UUID
    patient_id: UUID
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    orders_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposals: list[Proposal] = Field(min_length=1, max_length=36)

    @model_validator(mode="after")
    def validate_provenance(self):
        seen = set()
        for item in self.proposals:
            if item.id in seen:
                raise ValueError("Повторный ID предложения")
            seen.add(item.id)
            if item.evidence_status != "unverified_ai":
                raise ValueError("Агент может присылать только непроверенные AI-предложения")
            if item.kind == "demo_test":
                raise ValueError("Учебные тесты не выдаются за валидированные шкалы")
            if item.kind == "medication" and item.order is not None:
                if not item.order.active_ingredient:
                    raise ValueError("Не указано действующее вещество")
        return self
