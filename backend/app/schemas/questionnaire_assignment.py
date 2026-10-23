"""Непересекающиеся контракты для врача и пациента."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class AssignDemoTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_id: Literal["DEMO_ANX_7", "DEMO_DEP_9"]
    request_key: UUID


class CancelDemoTest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_revision: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)


class SubmitDemoTest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    answers: list[StrictInt] = Field(min_length=1, max_length=9)


class TestCatalogEntry(BaseModel):
    test_id: str
    version: str
    title: str
    description: str
    questions: list[str]
    answer_labels: list[str]
    demo_only: Literal[True]
    source: str
    interpretation: str
    critical_index: int | None


class TestResultRead(BaseModel):
    answers: list[int]
    total_score: int
    critical_flag: bool
    submitted_at: datetime


class TestAssignmentRead(BaseModel):
    id: str
    test_id: str
    test_version: str
    title: str
    status: Literal["assigned", "completed", "cancelled"]
    revision: int
    created_at: datetime
    completed_at: datetime | None
    result: TestResultRead | None = None


class DoctorTestAssignmentRead(TestAssignmentRead):
    patient_id: str
    assigned_by_id: str
    cancelled_at: datetime | None
    cancel_reason: str | None
    alert_id: str | None = None
