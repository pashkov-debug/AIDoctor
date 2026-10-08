from app.models import Encounter
from app.repositories.encounter import EncounterRepository
from app.repositories.patient import PatientRepository
from app.schemas.encounter import (
    EncounterCreate,
    EncounterListResponse,
    EncounterRead,
)
from sqlalchemy.orm import Session


class EncounterNotFoundError(LookupError):
    pass


class EncounterPatientNotFoundError(LookupError):
    pass


class EncounterService:
    def __init__(self, session: Session) -> None:
        self._session = session

        self._encounter_repository = EncounterRepository(session)

        self._patient_repository = PatientRepository(session)

    def create_encounter(
        self,
        patient_id: str,
        payload: EncounterCreate,
    ) -> EncounterRead:
        patient = self._patient_repository.get_by_id(patient_id)

        if patient is None:
            raise EncounterPatientNotFoundError(patient_id)

        encounter_payload = {
            "complaints": payload.complaints,
            "functional_impact": payload.functional_impact,
            "clinician_question": payload.clinician_question,
        }

        try:
            encounter = self._encounter_repository.create(
                patient_id=patient_id,
                reason=payload.reason,
                payload=encounter_payload,
                occurred_at=payload.occurred_at,
            )

            self._session.commit()
            self._session.refresh(encounter)

        except Exception:
            self._session.rollback()
            raise

        return self._to_read_model(encounter)

    def get_encounter(
        self,
        encounter_id: str,
    ) -> EncounterRead:
        encounter = self._encounter_repository.get_by_id(encounter_id)

        if encounter is None:
            raise EncounterNotFoundError(encounter_id)

        return self._to_read_model(encounter)

    def list_patient_encounters(
        self,
        patient_id: str,
    ) -> EncounterListResponse:
        patient = self._patient_repository.get_by_id(patient_id)

        if patient is None:
            raise EncounterPatientNotFoundError(patient_id)

        encounters = self._encounter_repository.list_by_patient(patient_id)

        return EncounterListResponse(
            items=[self._to_read_model(encounter) for encounter in encounters],
            total=len(encounters),
        )

    @staticmethod
    def _to_read_model(
        encounter: Encounter,
    ) -> EncounterRead:
        payload = encounter.payload_json or {}

        return EncounterRead(
            id=encounter.id,
            patient_id=encounter.patient_id,
            occurred_at=encounter.occurred_at,
            reason=encounter.reason,
            status=encounter.status,
            complaints=payload.get(
                "complaints",
                [],
            ),
            functional_impact=payload.get("functional_impact"),
            clinician_question=payload.get("clinician_question"),
            created_at=encounter.created_at,
        )
