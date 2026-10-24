"""Отдельный серверный seed ТОЛЬКО для выделенной aidoctor_synthetic.

Сохраняет действующие ограничения локальных seed_ui2a/ui2b/ui5.
Не переносит и не удаляет данные, работает идемпотентно.
"""

import argparse
import os
from datetime import UTC, datetime

from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from app.schemas.safety_alert import SafetyAlertCreate
from app.services.safety_alerts import create_alert
from backend.scripts.seed_ui2a_synthetic import seed_patient_timeline
from backend.scripts.seed_ui2b_synthetic import (
    FIRST_EVENTS,
    FIRST_OBSERVATIONS,
    FIRST_VISITS,
    SECOND_EVENTS,
    SECOND_OBSERVATIONS,
    SECOND_VISITS,
    get_or_create_second_patient,
    seed_extra_records,
)
from backend.scripts.seed_ui5_clinical_scenarios import (
    CRITICAL_ALERT_KEY,
    seed_all,
)
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

DATABASE_NAME = "aidoctor_synthetic"
FIRST_ALIAS = "Синтетическая С-001 — тревога и сон"
ACCOUNTS = (
    ("doctor_ui1", "doctor", "DEMO_DOCTOR_PASSWORD"),
    ("patient_ui1", "patient", "DEMO_PATIENT_PASSWORD"),
    ("admin_ui1", "admin", "DEMO_ADMIN_PASSWORD"),
)


def require_safe_target(app_env: str, database_url: str, actual_db: str) -> None:
    """Никогда не запускать на локальной/рабочей БД или через иной хост."""
    url = make_url(database_url)
    if not (
        app_env == "test"
        and url.drivername == "postgresql+psycopg"
        and url.host == "postgres"
        and url.database == DATABASE_NAME
        and actual_db == DATABASE_NAME
    ):
        raise ValueError("Требуется APP_ENV=test и отдельная postgres/aidoctor_synthetic")


def _credentials() -> dict[str, str]:
    result = {}
    for username, _role, env_name in ACCOUNTS:
        password = os.environ.get(env_name, "")
        if len(password) < 20:
            raise ValueError(f"{env_name}: нужно минимум 20 символов")
        result[username] = password
    if len(set(result.values())) != len(result):
        raise ValueError("Пароли демонстрационных ролей должны отличаться")
    return result


def _check_existing(session: Session) -> None:
    allowed = {row[0] for row in ACCOUNTS}
    unknown = session.scalars(select(User.username).where(User.username.notin_(allowed))).all()
    if unknown:
        raise ValueError("База содержит посторонние учётные записи; seed запрещён")
    patients = session.scalars(select(Patient)).all()
    if any(
        record.deleted_at is not None
        or (record.demographics_json or {}).get("synthetic") is not True
        for record in patients
    ):
        raise ValueError("Найдена несинтетическая/удалённая карточка; seed запрещён")


def _account(session: Session, username: str, role: str, password: str) -> User:
    existing = session.scalar(select(User).where(User.username == username).with_for_update())
    if existing:
        if existing.role != role:
            raise ValueError(f"Конфликт роли для {username}")
        if not verify_password(password, existing.password_hash):
            raise ValueError(
                f"Пароль {username} не соответствует существующему аккаунту. "
                "Не менять .env.test на работающей БД без процедуры ротации."
            )
        return existing
    user = User(username=username, role=role, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    return user


def _first_patient(session: Session, doctor: User, account: User) -> Patient:
    patient = session.scalar(select(Patient).where(Patient.user_id == account.id).with_for_update())
    if patient is None:
        patient = Patient(
            user_id=account.id,
            alias=FIRST_ALIAS,
            demographics_json={"synthetic": True, "scenario": "anxiety_sleep"},
        )
        session.add(patient)
        session.flush()
    elif patient.deleted_at is not None or (
        patient.demographics_json or {}
    ).get("synthetic") is not True:
        raise ValueError("Карточка patient_ui1 не является действующей синтетической")
    linked = session.scalar(
        select(DoctorPatient.id).where(
            DoctorPatient.doctor_id == doctor.id,
            DoctorPatient.patient_id == patient.id,
        )
    )
    if linked is None:
        session.add(DoctorPatient(doctor_id=doctor.id, patient_id=patient.id))
        session.flush()
    return patient


def populate(session: Session) -> None:
    actual = session.scalar(text("SELECT current_database()"))
    require_safe_target(settings.app_env, settings.database_url, actual)
    session.execute(text("SELECT pg_advisory_xact_lock(20261024, 1)"))
    _check_existing(session)
    passwords = _credentials()
    users = {
        username: _account(session, username, role, passwords[username])
        for username, role, _env in ACCOUNTS
    }
    doctor = users["doctor_ui1"]
    first = _first_patient(session, doctor, users["patient_ui1"])
    anchor = datetime.now(UTC)
    seed_patient_timeline(session, first, anchor)
    seed_extra_records(
        session, first, anchor, "anxiety",
        FIRST_VISITS, FIRST_EVENTS, FIRST_OBSERVATIONS,
    )
    second = get_or_create_second_patient(session, doctor)
    seed_extra_records(
        session, second, anchor, "mood",
        SECOND_VISITS, SECOND_EVENTS, SECOND_OBSERVATIONS,
    )
    third, totals = seed_all(session, doctor, first, second, anchor)
    session.commit()
    # Сервис создаёт Safety Alert + Outbox отдельной транзакцией.
    alert = create_alert(
        session,
        third.id,
        doctor.id,
        SafetyAlertCreate(reason_code="urgent_attention", priority="urgent"),
        idempotency_key=CRITICAL_ALERT_KEY,
    )
    print("Три синтетических сценария подготовлены.")
    print(f"Добавления UI-5: {totals}; сигнал: {alert.status}")
    print("Учётные записи: doctor_ui1, patient_ui1, admin_ui1 (пароли не выводятся).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Синтетические пациенты на выделенном VDS")
    parser.add_argument("--apply", action="store_true", help="Разрешить запись")
    args = parser.parse_args()
    if not args.apply:
        print("Только проверка: для наполнения используйте --apply.")
        return
    from app.db.session import SessionLocal

    with SessionLocal() as session:
        try:
            populate(session)
        except Exception:
            session.rollback()
            raise


if __name__ == "__main__":
    main()
