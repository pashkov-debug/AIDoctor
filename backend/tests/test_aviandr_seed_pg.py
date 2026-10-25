"""Проверка транзакционного и идемпотентного импорта в отдельную test-БД."""

from app.models.access import DoctorPatient, User
from app.models.clinical_entry_audit import ClinicalEntryAudit
from app.models.clinical_order import ClinicalOrder, ClinicalOrderAudit
from app.models.encounter import Encounter
from app.models.history_event import HistoryEvent
from app.models.medical_record import MedicalObservation
from app.models.patient import Patient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.scripts.seed_aviandr_case import load_case, seed_case


def _count(db, model, patient_id):
    return db.scalar(select(func.count()).select_from(model).where(model.patient_id == patient_id))


def test_import_by_weeks_is_idempotent_without_touching_other_patients(pg_engine):
    case = load_case()
    with Session(pg_engine) as db:
        doctor = User(username="doctor_ui1", role="doctor", password_hash="unused")
        db.add(doctor)
        db.flush()
        other = Patient(alias="Действующая карта", demographics_json={"synthetic": True})
        db.add(other)
        db.commit()
        other_id = other.id

        first = seed_case(db, case, doctor, through_week=0)
        db.commit()
        patient_id = first["patient_id"]
        assert first["patient_created"] == 1
        assert first["visits_created"] == 1
        assert first["history_created"] == 12
        assert first["observations_created"] == 18
        assert first["order_drafts_created"] == 1
        assert _count(db, Encounter, patient_id) == 1
        draft = db.scalar(select(ClinicalOrder).where(ClinicalOrder.patient_id == patient_id))
        assert draft.status == "draft"
        assert draft.approved_by_id is None
        assert draft.approved_at is None
        assert draft.times_local is None

        again = seed_case(db, case, doctor, through_week=0)
        db.commit()
        assert not any(
            again[key]
            for key in (
                "patient_created",
                "visits_created",
                "history_created",
                "observations_created",
                "order_drafts_created",
            )
        )

        final = seed_case(db, case, doctor, through_week=8)
        db.commit()
        assert final["patient_created"] == 0
        assert final["visits_created"] == 8
        assert _count(db, Encounter, patient_id) == 9
        assert _count(db, HistoryEvent, patient_id) == 44
        assert _count(db, MedicalObservation, patient_id) == 72
        assert _count(db, ClinicalOrder, patient_id) == 1
        assert db.scalar(select(func.count(ClinicalOrderAudit.id))) == 1
        assert db.scalar(select(func.count(ClinicalEntryAudit.id))) == 44 + 72
        assert db.scalar(select(func.count(DoctorPatient.id))) == 1
        assert db.get(Patient, other_id).alias == "Действующая карта"

        stable = seed_case(db, case, doctor, through_week=8)
        db.commit()
        assert stable["visits_created"] == stable["history_created"] == 0
        assert stable["observations_created"] == stable["order_drafts_created"] == 0
        assert db.get(Patient, patient_id).demographics_json["demo_featured"] is True
