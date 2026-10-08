from datetime import datetime

from app.models import Encounter
from sqlalchemy import select
from sqlalchemy.orm import Session


class EncounterRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        patient_id: str,
        reason: str,
        payload: dict,
        occurred_at: datetime | None = None,
    ) -> Encounter:
        encounter = Encounter(
            patient_id=patient_id,
            reason=reason,
            payload_json=payload,
        )

        if occurred_at is not None:
            encounter.occurred_at = occurred_at

        self._session.add(encounter)
        self._session.flush()

        return encounter

    def get_by_id(
        self,
        encounter_id: str,
    ) -> Encounter | None:
        statement = select(Encounter).where(Encounter.id == encounter_id)

        return self._session.scalar(statement)

    def list_by_patient(
        self,
        patient_id: str,
    ) -> list[Encounter]:
        statement = (
            select(Encounter)
            .where(Encounter.patient_id == patient_id)
            .order_by(Encounter.occurred_at.desc())
        )

        return list(self._session.scalars(statement).all())
