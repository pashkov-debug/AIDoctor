from app.db.base import Base
from app.models import (
    Encounter,
    HistoryEvent,
    Patient,
    QuestionnaireResponse,
    User,
    DoctorPatient,
    AuthSession,
    MedicalObservation,
    MedicalAttachment,
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
