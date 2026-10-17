"""Единая SQLAlchemy Metadata, доступная Alembic и PostgreSQL-тестам."""

from app.db.base import Base
from app.models import (
    AuthSession,
    ContextSnapshot,
    DoctorPatient,
    Encounter,
    HistoryEvent,
    MedicalAttachment,
    MedicalObservation,
    Patient,
    QuestionnaireResponse,
    User,
)

REGISTERED_MODELS = (
    Patient,
    Encounter,
    QuestionnaireResponse,
    User,
    DoctorPatient,
    AuthSession,
    MedicalObservation,
    MedicalAttachment,
    HistoryEvent,
    ContextSnapshot,
)

metadata = Base.metadata

__all__ = ["REGISTERED_MODELS", "metadata"]
