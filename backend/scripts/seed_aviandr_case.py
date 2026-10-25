"""Идемпотентный импорт восьминедельного синтетического кейса ГТР.

Наполняет существующие сущности; не меняет схемы БД, не удаляет данные,
не создаёт AI-ответов и не утверждает лекарственные назначения.
CLI: python -m backend.scripts.seed_aviandr_case --check
     python -m backend.scripts.seed_aviandr_case --apply --through-week 8
"""

import argparse
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.models.access import DoctorPatient, User
from app.models.clinical_entry_audit import ClinicalEntryAudit
from app.models.clinical_order import ClinicalOrder, ClinicalOrderAudit
from app.models.encounter import Encounter
from app.models.history_event import HistoryEvent
from app.models.medical_record import MedicalObservation
from app.models.patient import Patient
from app.schemas.clinical_order import OrderRead
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

FIXTURE = Path(__file__).resolve().parents[1] / "demo_cases/aviandr_gad_8weeks_v1.json"
SOURCE_KEY = "synthetic:aviandr:2026-10-25:v1"
EXPECTED_DOCUMENT_SHA256 = "3852ef0dac668fac01f686b86e79387086478165468f914d10dc4b736e0098ee"
TARGET_DATABASE = "aidoctor_synthetic"
START = date(2026, 8, 3)
END = date(2026, 9, 28)
MOSCOW = ZoneInfo("Europe/Moscow")
SCORE_MAXIMUMS = {"GAD-7": 21, "HAM-A": 56, "PHQ-9": 27, "ISI": 28}


def clinical_time(day: str | date) -> datetime:
    """Историческая дата события; дата импорта остаётся в created_at."""
    value = date.fromisoformat(day) if isinstance(day, str) else day
    return datetime.combine(value, time(12, 0), tzinfo=MOSCOW)


def load_case(path: Path = FIXTURE) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != "aidoctor.demo.case.v1":
        raise ValueError("Неподдерживаемая версия кейса")
    if data.get("seed_key") != SOURCE_KEY:
        raise ValueError("Изменён идентификатор импортируемого кейса")
    if data["source"].get("sha256") != EXPECTED_DOCUMENT_SHA256:
        raise ValueError("Изменён SHA-256 исходного DOCX: требуется новая версия кейса")
    visits, metrics = data["weekly_visits"], data["dynamics"]
    if len(visits) != 9 or len(metrics) != 9 or len(data["patient_diary"]) != 10:
        raise ValueError("Ожидались 9 визитов, 9 точек шкал и 10 записей дневника")
    if [v["week"] for v in visits] != list(range(9)):
        raise ValueError("Недели визитов должны идти от 0 до 8")
    for n, (visit, point) in enumerate(zip(visits, metrics, strict=True)):
        expected = START + timedelta(days=n * 7)
        if visit["date"] != expected.isoformat() or point["date"] != visit["date"]:
            raise ValueError("Нарушена календарная последовательность кейса")
        if point["week"] != n:
            raise ValueError("Неделя шкал не совпадает с неделей визита")
        for scale, maximum in SCORE_MAXIMUMS.items():
            value = point[scale]
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError(f"Неверное значение {scale} на неделе {n}")
        if not 0 < float(point["sleep_hours"]) <= 24:
            raise ValueError("Недопустимая длительность сна")
    for entry in data["patient_diary"]:
        d = date.fromisoformat(entry["date"])
        if not START <= d <= END or not 0 <= entry["anxiety_score_0_10"] <= 10:
            raise ValueError("Дневник пациента содержит некорректные значения")
    if len(data["laboratory_followup"]) != 7:
        raise ValueError("Ожидалось 7 показателей лабораторной/клинической динамики")
    for lab in data["laboratory_followup"]:
        if set(lab["values"]) != {"2026-08-03", "2026-08-31", "2026-09-28"}:
            raise ValueError("Неполная динамика контроля безопасности")
    return data


def require_safe_target(environment: str, url: str, actual_database: str) -> None:
    parsed = make_url(url)
    if not (
        environment == "test"
        and parsed.drivername == "postgresql+psycopg"
        and parsed.database == TARGET_DATABASE
        and actual_database == TARGET_DATABASE
    ):
        raise ValueError(
            "Импорт разрешён только при APP_ENV=test и подключении к "
            "выделенной PostgreSQL/aidoctor_synthetic"
        )


def _patient(db: Session, case: dict, doctor: User) -> tuple[Patient, bool]:
    alias = case["patient"]["alias"]
    rows = list(db.scalars(select(Patient).where(Patient.alias == alias).with_for_update()))
    if len(rows) > 1:
        raise ValueError("Несколько пациентов с демонстрационным псевдонимом")
    expected = {
        **case["patient"]["demographics"],
        "case_source_ref": SOURCE_KEY,
        "source_document_sha256": case["source"]["sha256"],
        "imported_by_doctor_id": doctor.id,
    }
    if rows:
        patient = rows[0]
        if patient.deleted_at is not None or patient.demographics_json != expected:
            raise ValueError("Карта с этим псевдонимом отличается от исходной: импорт остановлен")
        created = False
    else:
        patient = Patient(alias=alias, demographics_json=expected)
        db.add(patient)
        db.flush()
        created = True
    link = db.scalar(
        select(DoctorPatient.id).where(
            DoctorPatient.doctor_id == doctor.id, DoctorPatient.patient_id == patient.id
        )
    )
    if link is None:
        db.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        db.flush()
    return patient, created


def _encounters(db: Session, patient_id: str, case: dict, through_week: int) -> tuple[dict, int]:
    stored = list(db.scalars(select(Encounter).where(Encounter.patient_id == patient_id)))
    by_key = {}
    for item in stored:
        k = item.payload_json.get("seed_key") if isinstance(item.payload_json, dict) else None
        if k and k.startswith(SOURCE_KEY + ":"):
            if k in by_key:
                raise ValueError(f"Два визита с одним seed_key: {k}")
            by_key[k] = item
    count = 0
    visits = {}
    for week in case["weekly_visits"][: through_week + 1]:
        key = f"{SOURCE_KEY}:visit:{week['week']}"
        payload = {
            "seed_key": key,
            "synthetic": True,
            "complaints": [week["subjective"]],
            "functional_impact": None,
            "clinician_question": None,
            "week": week["week"],
            "source": case["source"]["document_title"],
        }
        values = {
            "reason": (
                "Первичный приём" if week["week"] == 0 else f"Контроль — неделя {week['week']}"
            ),
            "status": "draft",
            "occurred_at": clinical_time(week["date"]),
            "payload_json": payload,
        }
        prior = by_key.get(key)
        if prior:
            if any(getattr(prior, name) != value for name, value in values.items()):
                raise ValueError(f"Исторический визит был изменён: {key}")
            visits[week["week"]] = prior
            continue
        record = Encounter(patient_id=patient_id, **values)
        db.add(record)
        db.flush()
        visits[week["week"]] = record
        count += 1
    return visits, count


def _history_specs(case: dict, through_week: int) -> list[dict]:
    source = case["source"]
    baseline = case["baseline"]
    case_profile = "; ".join(
        f"{entry['parameter']}: {entry['value']}" for entry in case["patient"]["clinical_profile"]
    )
    base_parts = [
        ("паспорт_и_цели", case_profile, "clinical"),
        ("анамнез", baseline["anamnesis"], "clinical"),
        ("осмотр", baseline["examination"], "clinical"),
        ("диагноз", case["patient"]["working_diagnosis"], "clinical"),
        (
            "дифференциальный_ряд",
            "Дифференциальные гипотезы (условные учебные оценки): "
            + "; ".join(
                f"{d['hypothesis']}: {d['reason']} ({d['training_assessment']})"
                for d in baseline["differential"]
            ),
            "clinical",
        ),
        ("ограничения_гипотез", baseline["clinical_limits"], "clinical"),
        ("план_v1", baseline["treatment_v1"], "treatment"),
        ("немедикаментозно", baseline["nonpharmacologic_plan"], "treatment"),
        ("безопасность", baseline["safety"], "clinical"),
        ("обследования", baseline["baseline_screening_context"], "clinical"),
    ]
    specs = []
    for name, note, category in base_parts:
        specs.append(
            {
                "key": f"{SOURCE_KEY}:history:baseline:{name}",
                "date": START.isoformat(),
                "week": 0,
                "category": category,
                "text": note,
                "section": "Начальное обследование",
            }
        )
    for week in case["weekly_visits"][: through_week + 1]:
        for field, category in [("subjective", "self_report"), ("clinical_assessment", "clinical")]:
            specs.append(
                {
                    "key": f"{SOURCE_KEY}:history:week:{week['week']}:{field}",
                    "date": week["date"],
                    "week": week["week"],
                    "category": category,
                    "text": week[field],
                    "section": "Дневники врача по неделям",
                }
            )
    cutoff = START + timedelta(days=through_week * 7)
    for entry in case["patient_diary"]:
        if date.fromisoformat(entry["date"]) > cutoff:
            continue
        specs.append(
            {
                "key": f"{SOURCE_KEY}:history:diary:{entry['date']}",
                "date": entry["date"],
                "week": None,
                "category": "self_report",
                "text": entry["text"],
                "section": "Самостоятельный дневник пациента",
                "anxiety_score_0_10": entry["anxiety_score_0_10"],
                "sleep_text": entry["sleep_text"],
            }
        )
    if through_week == 8:
        for name, note in case["final"].items():
            if name == "source_references":
                note = "\n".join(note)
            specs.append(
                {
                    "key": f"{SOURCE_KEY}:history:final:{name}",
                    "date": END.isoformat(),
                    "week": 8,
                    "category": "clinical",
                    "text": note,
                    "section": "Итог, прогноз и ограничения",
                }
            )
    # Исключаем повторные ключи ещё до записи.
    keys = [item["key"] for item in specs]
    if len(keys) != len(set(keys)):
        raise ValueError("Повторяющиеся ключи событий истории")
    for item in specs:
        item["source_title"] = source["document_title"]
    return specs


def _history(
    db: Session, patient_id: str, doctor_id: str, case: dict, visits: dict, through_week: int
) -> int:
    seen = {}
    for row in db.scalars(select(HistoryEvent).where(HistoryEvent.patient_id == patient_id)):
        if row.source_ref.startswith(SOURCE_KEY + ":"):
            if row.source_ref in seen:
                raise ValueError(f"Дубликат события: {row.source_ref}")
            seen[row.source_ref] = row
    newly_added = []
    for item in _history_specs(case, through_week):
        fact = {
            "text": item["text"],
            "synthetic": True,
            "source": item["source_title"],
            "section": item["section"],
        }
        for field in ("anxiety_score_0_10", "sleep_text"):
            if field in item:
                fact[field] = item[field]
        values = {
            "category": item["category"],
            "fact_json": fact,
            "occurred_at": clinical_time(item["date"]),
            "priority": "normal",
            "encounter_id": visits[item["week"]].id if item["week"] is not None else None,
        }
        row = seen.get(item["key"])
        if row:
            if row.supersedes_id is not None or any(
                getattr(row, name) != value for name, value in values.items()
            ):
                raise ValueError(f"Изменён исторический факт: {item['key']}")
            continue
        row = HistoryEvent(patient_id=patient_id, source_ref=item["key"], **values)
        db.add(row)
        newly_added.append(row)
    db.flush()
    for row in newly_added:
        db.add(
            ClinicalEntryAudit(
                patient_id=patient_id,
                actor_id=doctor_id,
                record_type="history_event",
                record_id=row.id,
                action="imported",
                source_ref=row.source_ref,
                details_json={
                    "method": "synthetic_document_import",
                    "document_sha256": case["source"]["sha256"],
                    "category": row.category,
                },
            )
        )
    db.flush()
    return len(newly_added)


def _observation_specs(case: dict, through_week: int) -> list[dict]:
    specs = []
    for point in case["dynamics"][: through_week + 1]:
        for scale, maximum in SCORE_MAXIMUMS.items():
            specs.append(
                {
                    "key": f"{SOURCE_KEY}:obs:{point['date']}:{scale}",
                    "day": point["date"],
                    "week": point["week"],
                    "code": scale,
                    "system": "historical-clinical-scale",
                    "value": {
                        "score": point[scale],
                        "max": maximum,
                        "source_kind": "documented_historical_total_without_item_responses",
                        "description": "Итоговый балл из синтетического документа, "
                        "не электронный тест",
                        "synthetic": True,
                    },
                }
            )
        specs.append(
            {
                "key": f"{SOURCE_KEY}:obs:{point['date']}:sleep_hours",
                "day": point["date"],
                "week": point["week"],
                "code": "Сон (часы)",
                "system": "patient-diary",
                "value": {
                    "score": point["sleep_hours"],
                    "unit": "ч",
                    "description": point["interpretation"],
                    "synthetic": True,
                },
            }
        )
    for index, lab in enumerate(case["baseline"]["baseline_laboratory"], start=1):
        specs.append(
            {
                "key": f"{SOURCE_KEY}:obs:baseline-lab:{index}",
                "day": START.isoformat(),
                "week": 0,
                "code": f"Исходное обследование: {lab['indicator']}",
                "system": "documented-laboratory",
                "value": {
                    "result_text": lab["result"],
                    "text": lab["result"],
                    "description": lab["interpretation"],
                    "synthetic": True,
                },
            }
        )
    cutoff = START + timedelta(days=through_week * 7)
    for index, lab in enumerate(case["laboratory_followup"], start=1):
        for day, raw_value in lab["values"].items():
            if date.fromisoformat(day) > cutoff:
                continue
            numeric = None
            if raw_value.isdigit():
                numeric = int(raw_value)
            val = {
                "result_text": raw_value,
                "description": lab["repeat_reason"],
                "synthetic": True,
                "source_kind": "documented_followup",
            }
            if numeric is not None:
                val["score"] = numeric
            else:
                val["text"] = raw_value
            specs.append(
                {
                    "key": f"{SOURCE_KEY}:obs:lab:{index}:{day}",
                    "day": day,
                    "week": (date.fromisoformat(day) - START).days // 7,
                    "code": lab["indicator"],
                    "system": "documented-laboratory",
                    "value": val,
                }
            )
    keys = [item["key"] for item in specs]
    if len(keys) != len(set(keys)):
        raise ValueError("Повторяющиеся идентификаторы наблюдений")
    return specs


def _observations(
    db: Session, patient_id: str, doctor_id: str, case: dict, visits: dict, through_week: int
) -> int:
    seen = {}
    for row in db.scalars(
        select(MedicalObservation).where(MedicalObservation.patient_id == patient_id)
    ):
        if row.source_ref and row.source_ref.startswith(SOURCE_KEY + ":"):
            if row.source_ref in seen:
                raise ValueError(f"Дубликат наблюдения: {row.source_ref}")
            seen[row.source_ref] = row
    newly_added = []
    for item in _observation_specs(case, through_week):
        values = {
            "code_system": item["system"],
            "code": item["code"],
            "observed_at": clinical_time(item["day"]),
            "value_json": item["value"],
            "encounter_id": visits[item["week"]].id,
        }
        prior = seen.get(item["key"])
        if prior:
            if prior.supersedes_id is not None or any(
                getattr(prior, name) != value for name, value in values.items()
            ):
                raise ValueError(f"Изменено исходное наблюдение: {item['key']}")
            continue
        row = MedicalObservation(patient_id=patient_id, source_ref=item["key"], **values)
        db.add(row)
        newly_added.append(row)
    db.flush()
    for row in newly_added:
        db.add(
            ClinicalEntryAudit(
                patient_id=patient_id,
                actor_id=doctor_id,
                record_type="medical_observation",
                record_id=row.id,
                action="imported",
                source_ref=row.source_ref,
                details_json={
                    "method": "synthetic_document_import",
                    "document_sha256": case["source"]["sha256"],
                    "code": row.code,
                },
            )
        )
    db.flush()
    return len(newly_added)


def _draft_order(db: Session, patient: Patient, doctor: User, case: dict) -> int:
    source = f"{SOURCE_KEY}:document_order_v1"
    request_key = str(uuid5(NAMESPACE_URL, f"{source}:{patient.id}:{doctor.id}"))
    candidates = list(
        db.scalars(
            select(ClinicalOrder)
            .where(
                ClinicalOrder.patient_id == patient.id,
                ClinicalOrder.source_reference == source,
            )
            .with_for_update()
        )
    )
    if len(candidates) > 1:
        raise ValueError("Повторные назначения исходного документа")
    if candidates:
        existing = candidates[0]
        if existing.author_id != doctor.id or existing.request_key != request_key:
            raise ValueError("Существующее назначение принадлежит другому импорту")
        # Врач вправе изменить или утвердить черновик после импорта.
        return 0
    params = dict(case["clinical_order_draft"])
    params["dose_value"] = Decimal(params["dose_value"])
    params["start_date"] = date.fromisoformat(params["start_date"])
    order = ClinicalOrder(
        patient_id=patient.id,
        author_id=doctor.id,
        request_key=request_key,
        status="draft",
        version=1,
        source_reference=source,
        **params,
    )
    db.add(order)
    db.flush()
    db.add(
        ClinicalOrderAudit(
            order_id=order.id,
            actor_id=doctor.id,
            action="document_import_draft",
            version=1,
            snapshot_json=OrderRead.model_validate(order, from_attributes=True).model_dump(
                mode="json"
            ),
        )
    )
    db.flush()
    return 1


def seed_case(
    db: Session,
    case: dict,
    doctor: User,
    through_week: int = 8,
    include_order_draft: bool = True,
) -> dict:
    """Данные добавляются в текущую транзакцию; только вызывающий делает commit."""
    if not 0 <= through_week <= 8:
        raise ValueError("Номер недели должен находиться между 0 и 8")
    if doctor.role != "doctor":
        raise ValueError("Импорт выполняется от имени врача")
    patient, created = _patient(db, case, doctor)
    visits, visits_count = _encounters(db, patient.id, case, through_week)
    result = {
        "patient_created": int(created),
        "visits_created": visits_count,
        "history_created": _history(db, patient.id, doctor.id, case, visits, through_week),
        "observations_created": _observations(
            db, patient.id, doctor.id, case, visits, through_week
        ),
        "order_drafts_created": (
            _draft_order(db, patient, doctor, case) if include_order_draft else 0
        ),
        "patient_id": patient.id,
        "doctor_id": doctor.id,
        "through_week": through_week,
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Импорт синтетического клинического случая Авиандр / ГТР"
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--check", action="store_true", help="Проверить источник без БД")
    selection.add_argument(
        "--apply", action="store_true", help="Записать новые строки в тестовую БД"
    )
    parser.add_argument("--through-week", type=int, default=8, choices=range(9))
    parser.add_argument("--doctor", default="doctor_ui1", help="Имя существующего врача")
    parser.add_argument(
        "--without-medication-draft",
        action="store_true",
        help="Не создавать исходный лекарственный черновик: для AI-сценария",
    )
    args = parser.parse_args()
    case = load_case()
    print(
        f"Источник: {case['source']['document_title']}; "
        f"SHA256: {case['source']['sha256']}; "
        f"цель: неделя {args.through_week}"
    )
    if not args.apply:
        print(
            f"План импорта: {args.through_week + 1} визитов, "
            f"{len(_history_specs(case, args.through_week))} записей истории, "
            f"{len(_observation_specs(case, args.through_week))} наблюдений, "
            f"{0 if args.without_medication_draft else 1} лекарственный черновик."
        )
        print("Проверка пройдена; запись в БД не выполнялась. Для импорта нужен --apply.")
        return
    # Подключаемся к БД только после проверки конфигурации и источника.
    parsed = make_url(settings.database_url)
    if settings.app_env != "test" or parsed.database != TARGET_DATABASE:
        raise ValueError("Нужна тестовая база aidoctor_synthetic и APP_ENV=test")
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        try:
            current = db.scalar(text("SELECT current_database()"))
            require_safe_target(settings.app_env, settings.database_url, current)
            db.execute(text("SELECT pg_advisory_xact_lock(20261025, 3)"))
            doctor = db.scalar(select(User).where(User.username == args.doctor))
            if doctor is None:
                raise ValueError(f"Врач {args.doctor} не найден: сначала выполните базовый seed")
            result = seed_case(
                db,
                case,
                doctor,
                args.through_week,
                include_order_draft=not args.without_medication_draft,
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
    print("Импорт завершён:", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
