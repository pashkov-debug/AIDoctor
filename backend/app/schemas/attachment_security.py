"""Контракт статуса карантина: нет автоматического разрешения на парсинг."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AttachmentSecurityRead(BaseModel):
    attachment_id: str
    patient_id: str
    status: Literal["quarantined", "prechecked_quarantined", "rejected"]
    antivirus_status: Literal["not_scanned"] = "not_scanned"
    processing_allowed: Literal[False] = False
    quarantine_active: Literal[True] = True
    checked_at: datetime | None = None
    reason_code: str | None = None
