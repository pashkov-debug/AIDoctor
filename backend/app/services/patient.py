from app.models import Patient
from app.repositories.patient import PatientRepository
from app.schemas.patient import (
    PatientCreate,
    PatientListResponse,
    PatientRead,
)
from sqlalchemy.orm import Session


class PatientNotFoundError(LookupError):
    pass


class PatientService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = PatientRepository(session)

    def create_patient(
        self,
        payload: PatientCreate,
    ) -> PatientRead:
        try:
            patient = self._repository.create(
                alias=payload.alias,
                demographics=payload.demographics,
            )

            self._session.commit()
            self._session.refresh(patient)

        except Exception:
            self._session.rollback()
            raise

        return self._to_read_model(patient)

    def get_patient(
        self,
        patient_id: str,
    ) -> PatientRead:
        patient = self._repository.get_by_id(
            patient_id,
        )

        if patient is None:
            raise PatientNotFoundError(patient_id)

        return self._to_read_model(patient)

    def list_patients(
        self,
        *,
        search: str | None = None,
    ) -> PatientListResponse:
        patients = self._repository.list_active(
            search=search,
        )

        items = [self._to_read_model(patient) for patient in patients]

        return PatientListResponse(
            items=items,
            total=len(items),
        )

    @staticmethod
    def _to_read_model(
        patient: Patient,
    ) -> PatientRead:
        return PatientRead(
            id=patient.id,
            alias=patient.alias,
            demographics=patient.demographics_json,
            created_at=patient.created_at,
        )
