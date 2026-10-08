from app.models import Patient
from sqlalchemy import or_, select
from sqlalchemy.orm import Session


class PatientRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        alias: str,
        demographics: dict,
    ) -> Patient:
        patient = Patient(
            alias=alias,
            demographics_json=demographics,
        )

        self._session.add(patient)
        self._session.flush()

        return patient

    def get_by_id(
        self,
        patient_id: str,
    ) -> Patient | None:
        statement = select(Patient).where(
            Patient.id == patient_id,
            Patient.deleted_at.is_(None),
        )

        return self._session.scalar(statement)

    def list_active(
        self,
        *,
        search: str | None = None,
    ) -> list[Patient]:
        statement = (
            select(Patient).where(Patient.deleted_at.is_(None)).order_by(Patient.created_at.desc())
        )

        normalized_search = search.strip() if search else ""

        if normalized_search:
            pattern = f"%{normalized_search}%"

            statement = statement.where(
                or_(
                    Patient.alias.ilike(pattern),
                    Patient.id.ilike(pattern),
                )
            )

        return list(self._session.scalars(statement).all())
