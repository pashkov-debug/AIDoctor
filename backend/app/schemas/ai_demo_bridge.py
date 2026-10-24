"""Контракт обратной передачи синтетического AI-анализа из Site Builder."""

from typing import Literal
from uuid import UUID

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=180)
    rationale: str = Field(min_length=5, max_length=1200)
    confidence: Literal["low", "medium", "high", "uncertain"] = "uncertain"


class MedicationRisk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    medication: str = Field(min_length=2, max_length=180)
    risk: str = Field(min_length=5, max_length=1200)
    severity: Literal["low", "moderate", "high", "critical", "unknown"] = "unknown"


class ExaminationSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3, max_length=180)
    rationale: str = Field(min_length=5, max_length=1200)


class EvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=200)
    url: AnyHttpUrl
    relevance: str = Field(min_length=3, max_length=500)


class DemoAnalysisSubmit(BaseModel):
    """JSON для submit_demo_analysis; не является медицинским назначением."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["aidoctor_demo_analysis.v1"]
    request_id: UUID
    patient_id: UUID
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    orders_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["draft_requires_review"]
    summary: str = Field(min_length=20, max_length=4000)
    hypotheses: list[Hypothesis] = Field(default_factory=list, max_length=10)
    medication_risks: list[MedicationRisk] = Field(default_factory=list, max_length=12)
    missing_information: list[str] = Field(default_factory=list, max_length=12)
    suggested_examinations: list[ExaminationSuggestion] = Field(default_factory=list, max_length=12)
    sources: list[EvidenceSource] = Field(default_factory=list, max_length=15)
    limitations: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("missing_information", "limitations")
    @classmethod
    def validate_short_list(cls, values: list[str]) -> list[str]:
        if any(len(item.strip()) < 3 or len(item) > 500 for item in values):
            raise ValueError("Каждый элемент должен содержать от 3 до 500 символов")
        return values


class DemoAnalysisRead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["aidoctor_demo_analysis.v1"] = "aidoctor_demo_analysis.v1"
    request_id: str
    patient_id: str
    status: Literal["draft_requires_review"] = "draft_requires_review"
    submitted_at: str
    payload_sha256: str
    doctor_review_required: Literal[True] = True
    analysis: DemoAnalysisSubmit
