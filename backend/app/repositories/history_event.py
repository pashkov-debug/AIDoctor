from app.models import HistoryEvent
from sqlalchemy import select
from sqlalchemy.orm import Session


class HistoryEventRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        patient_id: str,
        encounter_id: str | None,
        category: str,
        fact: dict,
        priority: str,
        source_ref: str,
    ) -> HistoryEvent:
        event = HistoryEvent(
            patient_id=patient_id,
            encounter_id=encounter_id,
            category=category,
            fact_json=fact,
            priority=priority,
            source_ref=source_ref,
        )

        self._session.add(event)
        self._session.flush()

        return event

    def list_by_patient(
        self,
        patient_id: str,
    ) -> list[HistoryEvent]:
        statement = (
            select(HistoryEvent)
            .where(HistoryEvent.patient_id == patient_id)
            .order_by(HistoryEvent.occurred_at.desc())
        )

        return list(self._session.scalars(statement).all())
