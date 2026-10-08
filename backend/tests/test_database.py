from pathlib import Path

from app.db.base import Base
from app.db.session import create_database_engine
from app.models import (
    Encounter,
    HistoryEvent,
    Patient,
    QuestionnaireResponse,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


def test_longitudinal_record_can_be_persisted(tmp_path: Path) -> None:
    database_path = tmp_path / "test.db"

    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"

    engine = create_database_engine(database_url)

    Base.metadata.create_all(engine)

    with Session(engine) as session:
        patient = Patient(
            alias="P-001",
            demographics_json={
                "age_years": 34,
                "sex_at_birth": "female",
            },
        )

        session.add(patient)
        session.flush()

        encounter = Encounter(
            patient_id=patient.id,
            reason="initial",
            payload_json={
                "complaints": ["low_mood", "anxiety"],
            },
        )

        session.add(encounter)
        session.flush()

        questionnaire = QuestionnaireResponse(
            patient_id=patient.id,
            encounter_id=encounter.id,
            scale_id="DEMO_SCALE",
            item_scores_json=[1, 2, 1],
            total_score=4,
        )

        history_event = HistoryEvent(
            patient_id=patient.id,
            encounter_id=encounter.id,
            category="symptom",
            fact_json={
                "name": "sleep",
                "state": "worsened",
            },
            priority="normal",
            source_ref=f"local://encounter/{encounter.id}",
        )

        session.add_all(
            [
                questionnaire,
                history_event,
            ]
        )

        session.commit()

        stored_patient = session.scalar(select(Patient).where(Patient.id == patient.id))

        assert stored_patient is not None
        assert stored_patient.alias == "P-001"

        stored_encounter = session.scalar(
            select(Encounter).where(Encounter.patient_id == patient.id)
        )

        assert stored_encounter is not None

        stored_scale = session.scalar(
            select(QuestionnaireResponse).where(QuestionnaireResponse.encounter_id == encounter.id)
        )

        assert stored_scale is not None
        assert stored_scale.total_score == 4

        stored_event = session.scalar(
            select(HistoryEvent).where(HistoryEvent.patient_id == patient.id)
        )

        assert stored_event is not None
        assert stored_event.fact_json["name"] == "sleep"
