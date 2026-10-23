"""Контракт UI-4A: метаданные сохранённого запроса, НЕ ответ модели."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AIRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_key: UUID
    question: str = Field(min_length=10, max_length=5000)
    attachment_ids: list[UUID] = Field(default_factory=list, max_length=10)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Вопрос должен содержать не менее 10 символов")
        return value

    @field_validator("attachment_ids")
    @classmethod
    def unique_attachments(cls, value: list[UUID]) -> list[UUID]:
        if len(value) != len(set(value)):
            raise ValueError("Вложения не должны повторяться")
        return value


class AttachmentMetadata(BaseModel):
    id: str
    filename: str
    content_sha256: str
    status: Literal["excluded_unverified"] = "excluded_unverified"


class AIRequestRead(BaseModel):
    schema_version: Literal["ai_request.v1"] = "ai_request.v1"
    id: str
    patient_id: str
    doctor_id: str
    request_key: str
    question: str
    created_at: datetime
    context_snapshot_id: str
    context_sha256: str
    doctor_context: dict
    attachment_manifest: list[AttachmentMetadata]
    status: Literal["prepared"] = "prepared"
    revision: Literal[1] = 1
    ai_response_available: Literal[False] = False


class AIWorkspaceInfo(BaseModel):
    schema_version: Literal["ai_workspace.v1"] = "ai_workspace.v1"
    llm_connected: Literal[False] = False
    dispatch_enabled: Literal[False] = False
    attachment_content_allowed: Literal[False] = False
    reason: str = "LLM-провайдер и проверенный маршрут передачи вложений не подключены"
