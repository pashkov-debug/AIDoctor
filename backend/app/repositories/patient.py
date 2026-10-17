from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from sqlalchemy import false, or_, select
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
        patient = Patient(alias=alias, demographics_json=demographics)
        self._session.add(patient)
        self._session.flush()
        return patient

    def get_by_id(self, patient_id: str) -> Patient | None:
        return self._session.scalar(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.deleted_at.is_(None),
            )
        )

    def list_active(
        self,
        *,
        actor: User,
        search: str | None = None,
    ) -> list[Patient]:
        """SQL-фильтр прав применяется до чтения персональных данных."""
        statement = select(Patient).where(Patient.deleted_at.is_(None))

        if actor.role == "doctor":
            permitted_ids = select(DoctorPatient.patient_id).where(
                DoctorPatient.doctor_id == actor.id
            )
            statement = statement.where(Patient.id.in_(permitted_ids))
        elif actor.role == "patient":
            statement = statement.where(Patient.user_id == actor.id)
        elif actor.role != "admin":
            statement = statement.where(false())

        normalized_search = search.strip() if search else ""
        if normalized_search:
            pattern = f"%{normalized_search}%"
            statement = statement.where(
                or_(Patient.alias.ilike(pattern), Patient.id.ilike(pattern))
            )

        statement = statement.order_by(Patient.created_at.desc(), Patient.id)
        return list(self._session.scalars(statement).all())
