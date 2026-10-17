from app.db.base import Base
from app.models import (
    AuthSession,
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
)

metadata = Base.metadata

__all__ = [
    "REGISTERED_MODELS",
    "metadata",
]
