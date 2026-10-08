from datetime import datetime

from app.models import QuestionnaireResponse
from sqlalchemy import select
from sqlalchemy.orm import Session


class QuestionnaireRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        patient_id: str,
        encounter_id: str,
        scale_id: str,
        item_scores: list[int],
        total_score: int,
        measured_at: datetime | None = None,
    ) -> QuestionnaireResponse:
        response = QuestionnaireResponse(
            patient_id=patient_id,
            encounter_id=encounter_id,
            scale_id=scale_id,
            item_scores_json=item_scores,
            total_score=total_score,
        )

        if measured_at is not None:
            response.measured_at = measured_at

        self._session.add(response)
        self._session.flush()

        return response

    def list_by_patient(
        self,
        patient_id: str,
        *,
        scale_id: str | None = None,
    ) -> list[QuestionnaireResponse]:
        statement = (
            select(QuestionnaireResponse)
            .where(QuestionnaireResponse.patient_id == patient_id)
            .order_by(QuestionnaireResponse.measured_at.desc())
        )

        if scale_id:
            statement = statement.where(QuestionnaireResponse.scale_id == scale_id)

        return list(self._session.scalars(statement).all())
