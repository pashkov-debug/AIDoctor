"""Однократная/идемпотентная инициализация отдельной БД aidoctor_demo."""

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import Encounter, HistoryEvent, MedicalObservation, Patient  # noqa: F401
from demo_bridge.config import demo_url_from_env
from demo_bridge.contract import (
    ENCOUNTER_ID,
    HISTORY_ID,
    HISTORY_SECOND_ID,
    OBSERVATION_ID,
    PATIENT_ID,
    PUBLIC_ID,
    read_verified_case,
)

OCCURRED_AT = datetime(2026, 10, 19, 10, 0, tzinfo=UTC)


def seed_case(session: Session) -> bool:
    if session.get(Patient, PATIENT_ID) is not None:
        read_verified_case(session)
        return False

    session.add(
        Patient(
            id=PATIENT_ID,
            alias=PUBLIC_ID,
            demographics_json={"synthetic": True, "sex": "female", "age_years": 35},
        )
    )
    session.flush()
    session.add(
        Encounter(
            id=ENCOUNTER_ID,
            patient_id=PATIENT_ID,
            occurred_at=OCCURRED_AT,
            reason="Головная боль",
            status="completed",
            payload_json={
                "synthetic": True,
                "duration_months": 6,
                "episodes_per_month": 3,
                "episode_duration_hours": [4, 12],
                "note": "Синтетический учебный сценарий",
            },
        )
    )
    session.add_all(
        [
            HistoryEvent(
                id=HISTORY_ID,
                patient_id=PATIENT_ID,
                occurred_at=OCCURRED_AT,
                category="symptoms",
                priority="normal",
                source_ref="synthetic:history:headache",
                fact_json={
                    "synthetic": True,
                    "laterality": "unilateral_variable",
                    "character": "pulsating",
                    "nausea": True,
                    "photophobia": True,
                    "trigger": "sleep_deprivation",
                    "aura_reported": False,
                },
            ),
            HistoryEvent(
                id=HISTORY_SECOND_ID,
                patient_id=PATIENT_ID,
                occurred_at=OCCURRED_AT,
                category="safety_screen",
                priority="normal",
                source_ref="synthetic:history:safety",
                fact_json={
                    "synthetic": True,
                    "thunderclap_onset": False,
                    "other_red_flags": "not_assessed",
                    "neurological_exam": "not_recorded",
                    "medications": "not_recorded",
                },
            ),
            MedicalObservation(
                id=OBSERVATION_ID,
                patient_id=PATIENT_ID,
                observed_at=OCCURRED_AT,
                code_system="synthetic",
                code="headache_intensity",
                value_json={"synthetic": True, "value": 6, "scale": 10},
                source_ref="synthetic:observation:headache_intensity",
            ),
        ]
    )
    session.flush()
    read_verified_case(session)
    return True


def main() -> None:
    url = demo_url_from_env()
    engine = create_engine(url, pool_pre_ping=True)
    try:
        # Только строго aidoctor_demo. Не выполняем drop_all и не применяем Alembic.
        # Импорт моделей регистрирует SQLAlchemy metadata до create_all.
        Base.metadata.create_all(bind=engine)
        with Session(engine) as session, session.begin():
            created = seed_case(session)
        print("DEMO SEED OK:", "создан" if created else "уже существует")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
