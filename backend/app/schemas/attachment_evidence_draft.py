"""API-контракты ручных черновиков происхождения, без клинической интерпретации."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EvidenceDraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_locator: str = Field(min_length=1, max_length=120)
    excerpt: str = Field(min_length=1, max_length=2000)


class EvidenceDraftRead(BaseModel):
    id: str
    patient_id: str
    attachment_id: str
    created_by_id: str
    created_at: datetime
    source_locator: str
    excerpt: str
    attachment_sha256: str
    excerpt_sha256: str
    verification_status: Literal["unverified"] = "unverified"
    source_kind: Literal["manual"] = "manual"
