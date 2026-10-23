"""UI-5: реальные препараты, полностью вымышленные пациенты и данные.

Инкремент добавляет кейсы для независимой проверки будущим агентом:
- кандидаты-назначения сохраняются как ЗАБЛОКИРОВАННЫЕ черновики;
- проверочные выводы не сохраняются ни в истории, ни в черновике;
- независимый ответ находится только в документации, вне Context Builder.

Запуск: python -m backend.scripts.seed_ui5_clinical_scenarios [--apply]
"""

import argparse
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from app.core.config import settings
from app.models.access import DoctorPatient, User
from app.models.clinical_order import ClinicalOrder, ClinicalOrderAudit
from app.models.encounter import Encounter
from app.models.history_event import HistoryEvent
from app.models.medical_record import MedicalObservation
from app.models.patient import Patient
from app.schemas.clinical_order import OrderRead
from app.schemas.safety_alert import SafetyAlertCreate
from app.services.safety_alerts import create_alert
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.scripts.seed_ui2a_synthetic import ensure_local_development_target
from backend.scripts.seed_ui2b_synthetic import SECOND_ALIAS

SEED = "synthetic:ui5:v1"
CRITICAL_ALIAS = "Синтетическая С-003 — изменение состояния"
CANDIDATE_PREFIX = f"{SEED}:candidate:"
CRITICAL_ALERT_KEY = f"{SEED}:critical-alert"
DRUG_LABEL = "ZOLOFT (sertraline), DailyMed, setid=fda754f6-d0f3-4dce-a17a-927d64f912f7"

# Ни здесь, ни в записываемых полях нет эталонного ответа/вердикта.
ADDITIONAL_EVENTS = {
    "anxiety": (
        (
            -18,
            "self_report",
            "Со слов взрослого пациента: продолжает принимать фенелзин, схема и даты последнего приёма требуют сверки с назначением другого врача.",
        ),
        (
            -10,
            "clinician_note",
            "Список лекарств и даты приёма необходимо уточнить на очном визите.",
        ),
        (-5, "self_report", "Продолжаются периодические тревога и трудности засыпания."),
    ),
    "mood": (
        (
            -21,
            "self_report",
            "Взрослый пациент сообщает о снижении настроения и работоспособности.",
        ),
        (
            -13,
            "clinician_note",
            "Уточнить сопутствующие заболевания, лекарственную историю и переносимость ранее применявшихся препаратов.",
        ),
        (
            -3,
            "self_report",
            "Жалобы сохраняются; лечение в этом учебном случае требует проверки врачом.",
        ),
    ),
    "critical": (
        (-47, "self_report", "Сообщает о тревоге и ухудшении сна."),
        (-32, "self_report", "Отмечает нестабильное настроение и утомляемость."),
        (-17, "self_report", "Жалобы усилились; необходима повторная оценка состояния."),
        (-4, "self_report", "Сообщает об ухудшении самочувствия."),
        (
            -1,
            "symptom",
            "Со слов пациента появились мысли о причинении себе вреда. Требуется срочная оценка врачом; автоматических назначений нет.",
        ),
    ),
}
CRITICAL_VISITS = (
    (-47, "initial", ["Тревога", "Нарушенный сон"]),
    (-32, "follow_up", ["Утомляемость"]),
    (-17, "follow_up", ["Ухудшение самочувствия"]),
    (-1, "review", ["Острое изменение состояния, нужен врач"]),
)
CRITICAL_OBSERVATIONS = (
    (-47, "subjective_wellbeing", 6),
    (-32, "subjective_wellbeing", 5),
    (-17, "subjective_wellbeing", 3),
    (-1, "subjective_wellbeing", 1),
)


def _require_synthetic(patient: Patient) -> None:
    if (
        patient.deleted_at is not None
        or (patient.demographics_json or {}).get("synthetic") is not True
    ):
        raise ValueError("UI-5 разрешён только для действующих карточек synthetic=true")


def _attached_doctor(session: Session, doctor: User, patient: Patient) -> None:
    allowed = session.scalar(
        select(DoctorPatient.id).where(
            DoctorPatient.doctor_id == doctor.id,
            DoctorPatient.patient_id == patient.id,
        )
    )
    if allowed is None:
        raise ValueError(f"Врач не имеет доступа к {patient.alias}")


def _by_alias(session: Session, alias: str) -> Patient:
    rows = session.scalars(select(Patient).where(Patient.alias == alias).with_for_update()).all()
    if len(rows) != 1:
        raise ValueError(f"Ожидалась одна карточка: {alias}, найдено {len(rows)}")
    _require_synthetic(rows[0])
    return rows[0]


def _third_patient(session: Session, doctor: User) -> Patient:
    rows = session.scalars(
        select(Patient).where(Patient.alias == CRITICAL_ALIAS).with_for_update()
    ).all()
    if len(rows) > 1:
        raise ValueError("Дубли карточек С-003: требуется ручная проверка")
    if rows:
        patient = rows[0]
        _require_synthetic(patient)
    else:
        patient = Patient(
            alias=CRITICAL_ALIAS,
            demographics_json={"synthetic": True, "scenario": "acute_change_ui5"},
        )
        session.add(patient)
        session.flush()
    exists = session.scalar(
        select(DoctorPatient.id).where(
            DoctorPatient.doctor_id == doctor.id,
            DoctorPatient.patient_id == patient.id,
        )
    )
    if exists is None:
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        session.flush()
    return patient


def event_fact(scenario: str, index: int, narrative: str) -> dict:
    """Только исходные наблюдения; никаких диагностических выводов или подсказок."""
    fact = {"synthetic": True, "text": narrative, "source": "Вымышленная история UI-5"}
    if scenario == "anxiety" and index == 1:
        fact["medication_report"] = {
            "active_ingredient": "фенелзин",
            "status": "reported_current",
            "clinician_verified": False,
            "last_dose_date": None,
        }
    return fact


def seed_events(session: Session, patient: Patient, scenario: str, anchor: datetime) -> int:
    _require_synthetic(patient)
    existing = set(
        session.scalars(
            select(HistoryEvent.source_ref).where(HistoryEvent.patient_id == patient.id)
        ).all()
    )
    count = 0
    for index, (offset, category, narrative) in enumerate(ADDITIONAL_EVENTS[scenario], 1):
        key = f"{SEED}:{scenario}:event:{index}"
        if key in existing:
            continue
        session.add(
            HistoryEvent(
                patient_id=patient.id,
                category=category,
                fact_json=event_fact(scenario, index, narrative),
                source_ref=key,
                priority="urgent" if scenario == "critical" and offset == -1 else "normal",
                occurred_at=anchor + timedelta(days=offset),
            )
        )
        count += 1
    session.flush()
    return count


def seed_critical_timeline(session: Session, patient: Patient, anchor: datetime) -> dict[str, int]:
    _require_synthetic(patient)
    visits_seen = {
        rec.payload_json.get("seed_key")
        for rec in session.scalars(select(Encounter).where(Encounter.patient_id == patient.id))
        if isinstance(rec.payload_json, dict)
    }
    obs_seen = set(
        session.scalars(
            select(MedicalObservation.source_ref).where(MedicalObservation.patient_id == patient.id)
        ).all()
    )
    counts = {"visits": 0, "observations": 0}
    for index, (offset, reason, symptoms) in enumerate(CRITICAL_VISITS, 1):
        key = f"{SEED}:critical:visit:{index}"
        if key not in visits_seen:
            session.add(
                Encounter(
                    patient_id=patient.id,
                    status="draft",
                    reason=reason,
                    occurred_at=anchor + timedelta(days=offset),
                    payload_json={"seed_key": key, "synthetic": True, "complaints": symptoms},
                )
            )
            counts["visits"] += 1
    for index, (offset, code, score) in enumerate(CRITICAL_OBSERVATIONS, 1):
        key = f"{SEED}:critical:observation:{index}"
        if key not in obs_seen:
            session.add(
                MedicalObservation(
                    patient_id=patient.id,
                    code_system=SEED,
                    code=code,
                    observed_at=anchor + timedelta(days=offset),
                    value_json={
                        "synthetic": True,
                        "score": score,
                        "min": 0,
                        "max": 10,
                        "description": "Учебная самооценка, не диагностический тест",
                    },
                    source_ref=key,
                )
            )
            counts["observations"] += 1
    session.flush()
    return counts


def candidate_values(case: str, anchor: datetime) -> dict:
    """Структурированное предложение, а не подтверждённое лечение.

    Эталонная проверка находится только в docs/ui5_real_medicines.md.
    """
    if case not in {"1", "2"}:
        raise ValueError("Неизвестный учебный случай")
    return {
        "kind": "medication",
        "name": "Сертралин (учебный проект назначения)",
        "active_ingredient": "сертралин",
        "dosage_form": "таблетки",
        "strength": "100 мг" if case == "2" else "50 мг",
        "dose_value": Decimal("300") if case == "2" else Decimal("50"),
        "dose_unit": "мг",
        "route": "внутрь",
        "frequency_per_day": 1,
        "times_local": ["09:00"],
        "timezone": "Europe/Moscow",
        "start_date": anchor.date(),
        "duration_days": 30,
        "indication": "Учебное предложение для оценки врачом",
        "rationale": "Только учебный проект; клиническое обоснование требует проверки",
        "source_reference": f"{CANDIDATE_PREFIX}{case}",
    }


def seed_candidate(
    session: Session, patient: Patient, doctor: User, case: str, anchor: datetime
) -> int:
    """Создаёт неизменяемый тестовый черновик + аудит, никогда не утверждает."""
    _require_synthetic(patient)
    _attached_doctor(session, doctor, patient)
    request_key = str(uuid5(NAMESPACE_URL, f"{SEED}:{doctor.id}:{patient.id}:case:{case}"))
    existing = session.scalar(
        select(ClinicalOrder)
        .where(
            ClinicalOrder.author_id == doctor.id,
            ClinicalOrder.request_key == request_key,
        )
        .with_for_update()
    )
    if existing is not None:
        if (
            existing.patient_id != patient.id
            or existing.source_reference != f"{CANDIDATE_PREFIX}{case}"
            or existing.status != "draft"
        ):
            raise ValueError("Учебный черновик изменён/утверждён: остановка без перезаписи")
        return 0

    record = ClinicalOrder(
        patient_id=patient.id,
        author_id=doctor.id,
        request_key=request_key,
        status="draft",
        version=1,
        **candidate_values(case, anchor),
    )
    session.add(record)
    session.flush()
    snapshot = OrderRead.model_validate(record, from_attributes=True).model_dump(mode="json")
    session.add(
        ClinicalOrderAudit(
            order_id=record.id,
            actor_id=doctor.id,
            action="draft_created",
            version=1,
            snapshot_json=snapshot,
        )
    )
    session.flush()
    return 1


def seed_all(
    session: Session, doctor: User, first: Patient, second: Patient, anchor: datetime
) -> tuple[Patient, dict[str, int]]:
    """Запись без commit: вызывающий владеет транзакцией."""
    if doctor.role != "doctor":
        raise ValueError("Требуется врач")
    _require_synthetic(first)
    _require_synthetic(second)
    _attached_doctor(session, doctor, first)
    _attached_doctor(session, doctor, second)
    if anchor.utcoffset() is None:
        raise ValueError("Время должно содержать часовой пояс")
    third = _third_patient(session, doctor)
    result = {
        "events_a": seed_events(session, first, "anxiety", anchor),
        "events_b": seed_events(session, second, "mood", anchor),
        "events_c": seed_events(session, third, "critical", anchor),
    }
    result.update(seed_critical_timeline(session, third, anchor))
    result["candidate_a"] = seed_candidate(session, first, doctor, "1", anchor)
    result["candidate_b"] = seed_candidate(session, second, doctor, "2", anchor)
    return third, result


def main() -> None:
    parser = argparse.ArgumentParser(description="UI-5: реальные препараты, синтетические случаи")
    parser.add_argument("--apply", action="store_true", help="Изменить локальную aidoctor")
    args = parser.parse_args()

    from app.db.session import SessionLocal

    with SessionLocal() as session:
        database_name = session.scalar(text("SELECT current_database()"))
        ensure_local_development_target(settings.app_env, settings.database_url, database_name)
        session.execute(text("SELECT pg_advisory_xact_lock(20261023, 5)"))
        doctor = session.scalar(select(User).where(User.username == "doctor_ui1"))
        if doctor is None or doctor.role != "doctor":
            raise ValueError("Не найден doctor_ui1 с ролью doctor")
        first_user = session.scalar(select(User).where(User.username == "patient_ui1"))
        if first_user is None or first_user.role != "patient":
            raise ValueError("Не найден patient_ui1 с ролью patient")
        first = session.scalar(
            select(Patient).where(Patient.user_id == first_user.id).with_for_update()
        )
        if first is None:
            raise ValueError("Для patient_ui1 нет привязанной карточки")
        _require_synthetic(first)
        second = _by_alias(session, SECOND_ALIAS)
        _attached_doctor(session, doctor, first)
        _attached_doctor(session, doctor, second)
        print(f"БД: {database_name}; врач: {doctor.username}")
        print(f"Карточки: {first.alias}, {second.alias}, {CRITICAL_ALIAS}")
        print("Два лекарства будут созданы ТОЛЬКО как заблокированные учебные черновики.")
        if not args.apply:
            print("Режим проверки. Для записи: --apply")
            return

        third, counts = seed_all(session, doctor, first, second, datetime.now(UTC))
        session.commit()
        # Отдельная транзакция через существующий сервис, вместе с Outbox.
        # Если она не прошла, повторный --apply безопасно завершит создание.
        alert = create_alert(
            session,
            third.id,
            doctor.id,
            SafetyAlertCreate(reason_code="urgent_attention", priority="urgent"),
            idempotency_key=CRITICAL_ALERT_KEY,
        )
        print(f"Добавлено: {counts}")
        print(f"Критический учебный сигнал: {alert.id} (статус {alert.status})")
        print("Повторный запуск --apply не создаёт дубликаты.")


if __name__ == "__main__":
    main()
