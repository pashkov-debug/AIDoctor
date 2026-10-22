"""UI-2B: постоянные синтетические истории для двух пациентов локальной БД.

Не создаёт реальные назначения или диагностические заключения.
По умолчанию только проверяет цель; изменения — исключительно с --apply.
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
from sqlalchemy.orm import Session

from backend.scripts.seed_ui2a_synthetic import (
    ensure_local_development_target,
    seed_patient_timeline,
    select_target,
)

SEED_VERSION = "synthetic:ui2b:v1"
SECOND_ALIAS = "Синтетическая С-002 — сниженное настроение"

# Смещение в днях, тип визита, жалобы, влияние на повседневность, вопрос врачу.
FIRST_VISITS = (
    (-57, "initial", ("Тревога в конце рабочего дня", "Затруднения засыпания"), "moderate",
     "Уточнить динамику сна и влияние тревоги на активность."),
    (-49, "follow_up", ("Частые пробуждения", "Усталость утром"), "moderate",
     "Оценить регулярность сна по дневнику."),
    (-40, "review", ("Напряжение при нагрузке",), "moderate",
     "Сопоставить самочувствие с нагрузкой."),
    (-20, "follow_up", ("В отдельные дни беспокойство сохраняется",), "mild",
     "Проверить полноту анамнеза и факторы риска."),
    (-7, "review", ("Засыпание несколько легче", "Периодическая усталость"), "mild",
     "Какие сведения дополнительно собрать на приёме?"),
    (-1, "follow_up", ("Колебания напряжения",), "mild",
     "Требуется повторная врачебная оценка динамики."),
)
FIRST_EVENTS = (
    (-57, "self_report", "Начал вести учебный дневник сна; данные со слов пациента."),
    (-54, "symptom", "Засыпание по субъективной оценке занимает больше времени."),
    (-49, "self_report", "Сообщает о прерывистом сне в отдельные ночи."),
    (-43, "self_report", "Отмечал напряжение после рабочего дня."),
    (-40, "clinician_note", "Учебная запись: обсудить привычки сна на следующем приёме."),
    (-32, "self_report", "Некоторые дни ощущаются более спокойными."),
    (-26, "symptom", "На фоне нагрузки отмечал утомляемость."),
    (-20, "clinician_note", "Учебная запись: уточнить сопутствующие симптомы."),
    (-7, "self_report", "Сообщил об отдельных ночах с более лёгким засыпанием."),
    (-1, "self_report", "Самооценка состояния колеблется; нуждается в проверке врачом."),
)
FIRST_OBSERVATIONS = (
    (-57, "subjective_anxiety", 7),
    (-49, "subjective_anxiety", 6),
    (-40, "subjective_anxiety", 6),
    (-26, "subjective_anxiety", 5),
    (-20, "subjective_anxiety", 5),
    (-7, "subjective_anxiety", 4),
    (-1, "subjective_anxiety", 5),
)

SECOND_VISITS = (
    (-65, "initial", ("Снижение интереса к привычным занятиям", "Утомляемость"), "moderate",
     "Уточнить длительность симптомов и дифференциальные причины."),
    (-56, "follow_up", ("Трудности сосредоточения", "Нестабильный режим сна"), "moderate",
     "Оценить изменения нагрузки и сна."),
    (-48, "follow_up", ("Колебания настроения",), "moderate",
     "Собрать недостающую информацию о повседневной активности."),
    (-39, "review", ("Усталость к вечеру",), "moderate",
     "Проверить динамику субъективных оценок."),
    (-30, "follow_up", ("Сниженная активность в отдельные дни",), "moderate",
     "Уточнить факторы, связанные с утомлением."),
    (-22, "follow_up", ("В отдельные дни легче выполнять привычные дела",), "mild",
     "Оценить устойчивость изменений."),
    (-15, "review", ("Трудности концентрации сохраняются",), "mild",
     "Обсудить возможные дополнительные обследования."),
    (-8, "follow_up", ("Настроение изменчивое",), "mild",
     "Повторно уточнить выраженность функциональных ограничений."),
    (-2, "review", ("Жалобы на утомляемость",), "mild",
     "Нужна очная оценка; автоматических диагнозов нет."),
)
SECOND_EVENTS = (
    (-65, "self_report", "Со слов пациента: снизился интерес к досугу."),
    (-61, "symptom", "Периодически отмечает усталость даже после отдыха."),
    (-56, "self_report", "Сообщил об изменчивой продолжительности сна."),
    (-52, "clinician_note", "Учебная запись: уточнить медицинские причины утомляемости."),
    (-48, "self_report", "Сложнее выполнять дела, требующие внимания."),
    (-43, "symptom", "Отмечает снижение концентрации при длительной работе."),
    (-39, "clinician_note", "Учебная запись: недостаточно данных для диагностического вывода."),
    (-30, "self_report", "Отмечал снижение активности в некоторые дни."),
    (-22, "self_report", "Сообщает об улучшении самочувствия в отдельные дни."),
    (-19, "symptom", "Вечерняя усталость сохраняется непостоянно."),
    (-15, "clinician_note", "Учебная запись: требуется врачебная интерпретация динамики."),
    (-8, "self_report", "Самооценка повседневной активности немного повысилась."),
    (-2, "self_report", "Утомляемость сохраняется; полноценная оценка впереди."),
)
SECOND_OBSERVATIONS = (
    (-65, "subjective_energy", 2),
    (-56, "subjective_energy", 3),
    (-48, "subjective_energy", 3),
    (-39, "subjective_energy", 4),
    (-30, "subjective_energy", 3),
    (-22, "subjective_energy", 5),
    (-15, "subjective_energy", 5),
    (-8, "subjective_energy", 6),
    (-2, "subjective_energy", 5),
)


def get_or_create_second_patient(session: Session, doctor: User) -> Patient:
    """Только синтетическая карточка. Никогда не присваиваем существующий аккаунт."""
    candidates = session.scalars(
        select(Patient).where(Patient.alias == SECOND_ALIAS).with_for_update()
    ).all()
    if len(candidates) > 1:
        raise ValueError("Несколько одноимённых карточек: требуется ручной разбор")
    if candidates:
        patient = candidates[0]
        if patient.deleted_at is not None:
            raise ValueError("Синтетическая карточка удалена; не восстанавливаем автоматически")
        if (patient.demographics_json or {}).get("synthetic") is not True:
            raise ValueError("Карточка с таким именем не помечена synthetic=true")
    else:
        patient = Patient(
            alias=SECOND_ALIAS,
            demographics_json={"synthetic": True, "scenario": "mood_monitoring"},
        )
        session.add(patient)
        session.flush()

    link = session.scalar(
        select(DoctorPatient.id).where(
            DoctorPatient.doctor_id == doctor.id,
            DoctorPatient.patient_id == patient.id,
        )
    )
    if link is None:
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        session.flush()
    return patient


def seed_extra_records(
    session: Session,
    patient: Patient,
    anchor: datetime,
    scenario: str,
    visits: tuple,
    events: tuple,
    observations: tuple,
) -> dict[str, int]:
    """Аддитивное заполнение без перезаписи текущих и прежних фактов."""
    if (patient.demographics_json or {}).get("synthetic") is not True:
        raise ValueError("Нельзя писать в карточку без synthetic=true")
    if anchor.tzinfo is None or anchor.utcoffset() is None:
        raise ValueError("Время должно быть timezone-aware")

    visits_seen = {
        p.payload_json.get("seed_key")
        for p in session.scalars(
            select(Encounter).where(Encounter.patient_id == patient.id)
        ).all()
        if isinstance(p.payload_json, dict)
    }
    events_seen = set(session.scalars(
        select(HistoryEvent.source_ref).where(HistoryEvent.patient_id == patient.id)
    ).all())
    observations_seen = set(session.scalars(
        select(MedicalObservation.source_ref).where(MedicalObservation.patient_id == patient.id)
    ).all())

    result = {"visits": 0, "events": 0, "observations": 0}
    for number, (offset, reason, complaints, impact, question) in enumerate(visits, 1):
        key = f"{SEED_VERSION}:{scenario}:visit:{number}"
        if key in visits_seen:
            continue
        session.add(Encounter(
            patient_id=patient.id, reason=reason, status="draft",
            occurred_at=anchor + timedelta(days=offset),
            payload_json={
                "seed_key": key, "synthetic": True, "complaints": list(complaints),
                "functional_impact": impact, "clinician_question": question,
            },
        ))
        result["visits"] += 1

    for number, (offset, category, narrative) in enumerate(events, 1):
        key = f"{SEED_VERSION}:{scenario}:event:{number}"
        if key in events_seen:
            continue
        session.add(HistoryEvent(
            patient_id=patient.id, category=category, encounter_id=None,
            fact_json={"synthetic": True, "text": narrative, "source": "Учебный сценарий UI-2B"},
            occurred_at=anchor + timedelta(days=offset),
            source_ref=key, priority="normal",
        ))
        result["events"] += 1

    for number, (offset, code, value) in enumerate(observations, 1):
        key = f"{SEED_VERSION}:{scenario}:observation:{number}"
        if key in observations_seen:
            continue
        session.add(MedicalObservation(
            patient_id=patient.id,
            code_system="synthetic:ui2b",
            code=code,
            observed_at=anchor + timedelta(days=offset),
            value_json={
                "score": value, "min": 0, "max": 10, "synthetic": True,
                "description": "Учебная субъективная оценка, не клинический опросник",
            },
            source_ref=key,
        ))
        result["observations"] += 1
    session.flush()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Два синтетических пациента UI-2B")
    parser.add_argument("--apply", action="store_true", help="Записать в локальную aidoctor")
    args = parser.parse_args()
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        current_db = session.execute(text("select current_database()")).scalar_one()
        ensure_local_development_target(settings.app_env, settings.database_url, current_db)
        # Сериализуем параллельные seed-запуски, чтобы не создавать вторую карточку дважды.
        session.execute(text("select pg_advisory_xact_lock(20261023, 2)"))
        first = select_target(session, "doctor_ui1", "patient_ui1")
        doctor = session.scalar(select(User).where(User.username == "doctor_ui1"))
        existing_second = session.scalars(
            select(Patient).where(Patient.alias == SECOND_ALIAS)
        ).all()
        if len(existing_second) > 1 or any(
            p.deleted_at is not None or (p.demographics_json or {}).get("synthetic") is not True
            for p in existing_second
        ):
            raise ValueError("Конфликт со второй карточкой: требуется ручная проверка")
        print(f"БД: {current_db}; врач: {doctor.username}; пациент 1: {first.alias}")
        print(f"Пациент 2: {SECOND_ALIAS} ({'существует' if existing_second else 'будет создан'})")
        if not args.apply:
            print("Проверка без изменений. Для создания/дополнения: --apply")
            return

        anchor = datetime.now(UTC)
        try:
            # Первую историю UI-2A восстанавливаем аддитивно, если её ещё не заполняли.
            first_base = seed_patient_timeline(session, first, anchor)
            first_extra = seed_extra_records(
                session, first, anchor, "anxiety", FIRST_VISITS, FIRST_EVENTS,
                FIRST_OBSERVATIONS,
            )
            second = get_or_create_second_patient(session, doctor)
            second_extra = seed_extra_records(
                session, second, anchor, "mood", SECOND_VISITS, SECOND_EVENTS,
                SECOND_OBSERVATIONS,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        print(f"Пациент 1 (UI-2A): {first_base}; дополнительные данные: {first_extra}")
        print(f"Пациент 2: {second.alias} ({second.id}); данные: {second_extra}")
        print("Готово. Повторный --apply добавит только недостающие записи.")


if __name__ == "__main__":
    main()
