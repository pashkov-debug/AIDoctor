from app.db.base import Base
from app.models import (
    Encounter,
    HistoryEvent,
    Patient,
    QuestionnaireResponse,
)

REGISTERED_MODELS = (
    Patient,
    Encounter,
    QuestionnaireResponse,
    HistoryEvent,
)

metadata = Base.metadata

__all__ = [
    "REGISTERED_MODELS",
    "metadata",
]
