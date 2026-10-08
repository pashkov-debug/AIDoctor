from app.models import HistoryEvent
from app.repositories.history_event import (
    HistoryEventRepository,
)
from app.repositories.patient import PatientRepository
from app.schemas.history_event import (
    HistoryEventList,
    HistoryEventRead,
)
from sqlalchemy.orm import Session


class HistoryPatientNotFoundError(LookupError):
    pass


class HistoryEventService:
    def __init__(
        self,
        session: Session,
    ) -> None:
        self._patient_repository = PatientRepository(session)

        self._history_repository = HistoryEventRepository(session)

    def list_patient_events(
        self,
        patient_id: str,
    ) -> HistoryEventList:
        patient = self._patient_repository.get_by_id(patient_id)

        if patient is None:
            raise HistoryPatientNotFoundError(patient_id)

        events = self._history_repository.list_by_patient(patient_id)

        return HistoryEventList(
            items=[self._to_read_model(event) for event in events],
            total=len(events),
        )

    @staticmethod
    def _to_read_model(
        event: HistoryEvent,
    ) -> HistoryEventRead:
        return HistoryEventRead(
            id=event.id,
            patient_id=event.patient_id,
            encounter_id=event.encounter_id,
            category=event.category,
            fact=event.fact_json,
            occurred_at=event.occurred_at,
            priority=event.priority,
            source_ref=event.source_ref,
            supersedes_id=event.supersedes_id,
            correction_reason=event.correction_reason,
            created_at=event.created_at,
        )
