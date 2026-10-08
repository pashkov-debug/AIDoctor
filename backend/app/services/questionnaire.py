from app.clinical.scales import (
    InvalidScaleResponseError,
    ScaleNotFoundError,
    get_scale_definition,
)
from app.models import QuestionnaireResponse
from app.repositories.encounter import EncounterRepository
from app.repositories.history_event import (
    HistoryEventRepository,
)
from app.repositories.questionnaire import (
    QuestionnaireRepository,
)
from app.schemas.questionnaire import (
    QuestionnaireResponseCreate,
    QuestionnaireResponseList,
    QuestionnaireResponseRead,
)
from sqlalchemy.orm import Session


class QuestionnaireEncounterNotFoundError(LookupError):
    pass


class QuestionnaireService:
    def __init__(
        self,
        session: Session,
    ) -> None:
        self._session = session

        self._encounter_repository = EncounterRepository(session)

        self._questionnaire_repository = QuestionnaireRepository(session)

        self._history_repository = HistoryEventRepository(session)

    def create_response(
        self,
        encounter_id: str,
        payload: QuestionnaireResponseCreate,
    ) -> QuestionnaireResponseRead:
        encounter = self._encounter_repository.get_by_id(encounter_id)

        if encounter is None:
            raise QuestionnaireEncounterNotFoundError(encounter_id)

        scale = get_scale_definition(payload.scale_id)

        total_score = scale.calculate_score(payload.item_scores)

        try:
            response = self._questionnaire_repository.create(
                patient_id=encounter.patient_id,
                encounter_id=encounter.id,
                scale_id=payload.scale_id,
                item_scores=payload.item_scores,
                total_score=total_score,
                measured_at=payload.measured_at,
            )

            self._history_repository.create(
                patient_id=encounter.patient_id,
                encounter_id=encounter.id,
                category="questionnaire",
                fact={
                    "scale_id": response.scale_id,
                    "total_score": response.total_score,
                },
                priority="normal",
                source_ref=(f"local://questionnaire/{response.id}"),
            )

            self._session.commit()
            self._session.refresh(response)

        except Exception:
            self._session.rollback()
            raise

        return self._to_read_model(response)

    def list_patient_responses(
        self,
        patient_id: str,
        *,
        scale_id: str | None = None,
    ) -> QuestionnaireResponseList:
        responses = self._questionnaire_repository.list_by_patient(
            patient_id,
            scale_id=scale_id,
        )

        return QuestionnaireResponseList(
            items=[self._to_read_model(response) for response in responses],
            total=len(responses),
        )

    @staticmethod
    def _to_read_model(
        response: QuestionnaireResponse,
    ) -> QuestionnaireResponseRead:
        return QuestionnaireResponseRead(
            id=response.id,
            patient_id=response.patient_id,
            encounter_id=response.encounter_id,
            scale_id=response.scale_id,
            item_scores=response.item_scores_json,
            total_score=response.total_score,
            measured_at=response.measured_at,
            created_at=response.created_at,
        )


__all__ = [
    "InvalidScaleResponseError",
    "QuestionnaireEncounterNotFoundError",
    "QuestionnaireService",
    "ScaleNotFoundError",
]
