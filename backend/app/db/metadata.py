"""Единая SQLAlchemy Metadata, доступная Alembic и PostgreSQL-тестам."""

from app.db.base import Base
from app.models import (
    AttachmentEvidenceDraft,
    AttachmentEvidenceReadAudit,
    AttachmentSecurityEvent,
    AttachmentSecurityReview,
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
    SafetyFollowup,
    SafetyInAppNotification,
    SafetyNotificationRoute,
    SafetyNotificationRouteEvent,
    SafetyOutbox,
    SafetyOutboxEvent,
    SafetyReadAudit,
    User,
)

REGISTERED_MODELS = (
    AttachmentEvidenceDraft,
    AttachmentEvidenceReadAudit,
    AttachmentSecurityEvent,
    AttachmentSecurityReview,
    Patient,
    Encounter,
    QuestionnaireResponse,
    User,
    DoctorPatient,
    AttachmentSecurityEvent,
    AttachmentSecurityReview,
    AuthSession,
    MedicalObservation,
    MedicalAttachment,
    HistoryEvent,
    ContextSnapshot,
    SafetyAlert,
    SafetyAlertEvent,
    SafetyAlertRequest,
    SafetyFollowup,
    SafetyInAppNotification,
    SafetyNotificationRoute,
    SafetyNotificationRouteEvent,
    SafetyOutbox,
    SafetyOutboxEvent,
    SafetyReadAudit,
)

metadata = Base.metadata

__all__ = ["REGISTERED_MODELS", "metadata"]
