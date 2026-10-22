"""Однократное/идемпотентное наполнение локальной aidoctor вымышленной историей UI-2A.

Запуск из корня: python -m backend.scripts.seed_ui2a_synthetic --apply
"""
import argparse
from datetime import UTC, datetime, timedelta

from app.core.config import settings
from app.models.access import DoctorPatient, User
from app.models.encounter import Encounter
from app.models.history_event import HistoryEvent
from app.models.medical_record import MedicalObservation
from app.models.patient import Patient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

SEED = "synthetic:ui2a:v1"
VISITS = (
    (-35, "initial", ["Беспокойство", "Трудности засыпания"], "moderate"),
    (-24, "follow_up", ["Периодическое напряжение", "Утомляемость"], "moderate"),
    (-12, "follow_up", ["Нестабильный сон"], "mild"),
    (-2, "review", ["Беспокойство в отдельные дни"], "mild"),
)
EVENTS = (
    (-35, "symptom", "Пациент описывает беспокойство и сложности со сном."),
    (-29, "self_report", "Синтетическая запись: отмечал трудности концентрации."),
    (-24, "symptom", "Сообщает о продолжающемся напряжении."),
    (-17, "self_report", "Отмечает несколько ночей с более спокойным сном."),
    (-12, "symptom", "Жалобы на сон сохраняются эпизодически."),
    (-2, "self_report", "Сообщает об изменчивом самочувствии; требуется оценка врача."),
)
OBSERVATIONS = (
    (-35, "subjective_sleep_quality", 3),
    (-17, "subjective_sleep_quality", 4),
    (-2, "subjective_sleep_quality", 5),
)


def ensure_local_development_target(app_env: str, database_url: str, database_name: str) -> None:
    """Запрет записи в production и в выделенную тестовую БД."""
    parsed = make_url(database_url)
    if not (
        app_env == "local"
        and parsed.drivername == "postgresql+psycopg"
        and parsed.host in {"localhost", "127.0.0.1"}
        and parsed.database == "aidoctor"
        and database_name == "aidoctor"
    ):
        raise ValueError("Seed разрешён только в локальной основной БД aidoctor при APP_ENV=local")


def select_target(session: Session, doctor_name: str, patient_name: str) -> Patient:
    doctor = session.scalar(select(User).where(User.username == doctor_name))
    account = session.scalar(select(User).where(User.username == patient_name))
    if doctor is None or doctor.role != "doctor":
        raise ValueError("Учётная запись врача не найдена или имеет другую роль")
    if account is None or account.role != "patient":
        raise ValueError("Учётная запись пациента не найдена или имеет другую роль")

    # Блокируем карточку до конца транзакции. Параллельные запуски не дублируют записи.
    patient = session.scalar(
        select(Patient).where(Patient.user_id == account.id).with_for_update()
    )
    if patient is None or patient.deleted_at is not None:
        raise ValueError("У пациента нет активной привязанной карточки")
    if (patient.demographics_json or {}).get("synthetic") is not True:
        raise ValueError("Нельзя наполнять карточку без явной метки synthetic=true")
    allowed = session.scalar(
        select(DoctorPatient.id).where(
            DoctorPatient.doctor_id == doctor.id,
            DoctorPatient.patient_id == patient.id,
        )
    )
    if allowed is None:
        raise ValueError("Врач не имеет связи с карточкой пациента")
    return patient


def seed_patient_timeline(
    session: Session, patient: Patient, reference: datetime
) -> dict[str, int]:
    """Добавляет только отсутствующие факты; транзакцию контролирует вызывающий код."""
    if (patient.demographics_json or {}).get("synthetic") is not True:
        raise ValueError("Нельзя изменять несинтетическую карточку")
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise ValueError("reference должен содержать временную зону")
    visits = session.scalars(
        select(Encounter).where(Encounter.patient_id == patient.id)
    ).all()
    by_key = {
        item.payload_json.get("seed_key"): item
        for item in visits
        if isinstance(item.payload_json, dict) and item.payload_json.get("seed_key")
    }
    created = {"visits": 0, "events": 0, "observations": 0}
    for index, (offset, reason, complaints, impact) in enumerate(VISITS, start=1):
        key = f"{SEED}:visit:{index}"
        if key in by_key:
            continue
        item = Encounter(
            patient_id=patient.id, reason=reason, status="draft",
            occurred_at=reference + timedelta(days=offset),
            payload_json={
                "seed_key": key, "synthetic": True,
                "complaints": complaints,
                "functional_impact": impact,
                "clinician_question": None,
            },
        )
        session.add(item)
        created["visits"] += 1

    event_refs = set(session.scalars(
        select(HistoryEvent.source_ref).where(HistoryEvent.patient_id == patient.id)
    ).all())
    for index, (offset, category, narrative) in enumerate(EVENTS, start=1):
        key = f"{SEED}:event:{index}"
        if key in event_refs:
            continue
        session.add(HistoryEvent(
            patient_id=patient.id, encounter_id=None, category=category,
            fact_json={"synthetic": True, "text": narrative, "source": "Учебный сценарий UI-2A"},
            priority="normal", source_ref=key,
            occurred_at=reference + timedelta(days=offset),
        ))
        created["events"] += 1

    obs_refs = set(session.scalars(
        select(MedicalObservation.source_ref).where(MedicalObservation.patient_id == patient.id)
    ).all())
    for index, (offset, code, value) in enumerate(OBSERVATIONS, start=1):
        key = f"{SEED}:observation:{index}"
        if key in obs_refs:
            continue
        session.add(MedicalObservation(
            patient_id=patient.id, code_system="synthetic:ui2a",
            code=code, observed_at=reference + timedelta(days=offset),
            value_json={
                "score": value, "min": 0, "max": 10, "synthetic": True,
                "description": (
                    "Учебная самооценка качества сна, не валидированная клиническая шкала"
                ),
            },
            source_ref=key,
        ))
        created["observations"] += 1
    session.flush()
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description="Синтетическая история в локальной aidoctor")
    parser.add_argument("--apply", action="store_true", help="Разрешить запись")
    parser.add_argument("--doctor", default="doctor_ui1")
    parser.add_argument("--patient", default="patient_ui1")
    args = parser.parse_args()
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        actual_db = session.execute(text("select current_database()")).scalar_one()
        ensure_local_development_target(settings.app_env, settings.database_url, actual_db)
        patient = select_target(session, args.doctor, args.patient)
        print(f"Локальная БД: {actual_db} | синтетический пациент: {patient.alias} ({patient.id})")
        if not args.apply:
            print("Режим просмотра. Для добавления 4 визитов, 6 событий и 3 наблюдений: --apply")
            return
        totals = seed_patient_timeline(session, patient, datetime.now(UTC))
        session.commit()
        print(f"Добавлено: {totals}. Повторный запуск не создаст дубликатов.")


if __name__ == "__main__":
    main()
