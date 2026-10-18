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
    SafetyAlert,
    SafetyAlertEvent,
    SafetyAlertRequest,
    SafetyInAppNotification,
    SafetyNotificationRoute,
    SafetyNotificationRouteEvent,
    SafetyOutbox,
    SafetyOutboxEvent,
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
    SafetyAlert,
    SafetyAlertEvent,
    SafetyAlertRequest,
    SafetyInAppNotification,
    SafetyNotificationRoute,
    SafetyNotificationRouteEvent,
    SafetyOutbox,
    SafetyOutboxEvent,
)

metadata = Base.metadata

__all__ = ["REGISTERED_MODELS", "metadata"]
