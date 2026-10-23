"""UI-5: транзакционные сценарии только на выделенной aidoctor_test."""

from datetime import UTC, datetime

import pytest
from app.models.access import DoctorPatient, User
from app.models.clinical_order import ClinicalOrder, ClinicalOrderAudit
from app.models.history_event import HistoryEvent
from app.models.patient import Patient
from app.models.safety_alert import SafetyAlert
from app.schemas.safety_alert import SafetyAlertCreate
from app.services.safety_alerts import create_alert
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.scripts.seed_ui5_clinical_scenarios import (
    CRITICAL_ALERT_KEY,
    SECOND_ALIAS,
    seed_all,
)


def test_ui5_real_drugs_seed_is_additive_and_repeatable(pg_engine) -> None:
    with Session(pg_engine) as db:
        doctor = User(username="ui5doc", role="doctor", password_hash="x")
        first = Patient(alias="UI5-A", demographics_json={"synthetic": True})
        second = Patient(alias=SECOND_ALIAS, demographics_json={"synthetic": True})
        db.add_all([doctor, first, second])
        db.flush()
        db.add_all(
            [
                DoctorPatient(doctor_id=doctor.id, patient_id=first.id),
                DoctorPatient(doctor_id=doctor.id, patient_id=second.id),
            ]
        )
        db.flush()
        anchor = datetime(2026, 10, 23, tzinfo=UTC)
        third, counts = seed_all(db, doctor, first, second, anchor)
        assert counts["candidate_a"] == counts["candidate_b"] == 1
        assert counts["visits"] == 4
        db.commit()

        again, counts2 = seed_all(db, doctor, first, second, anchor)
        assert again.id == third.id
        assert all(value == 0 for value in counts2.values())

        orders = db.scalars(select(ClinicalOrder).order_by(ClinicalOrder.request_key)).all()
        assert len(orders) == 2
        assert {o.status for o in orders} == {"draft"}
        assert {o.active_ingredient for o in orders} == {"сертралин"}
        assert db.scalar(select(func.count(ClinicalOrderAudit.id))) == 2
        assert db.scalar(select(func.count(HistoryEvent.id))) == (3 + 3 + 5)
        db.commit()

        alert = create_alert(
            db,
            third.id,
            doctor.id,
            SafetyAlertCreate(reason_code="urgent_attention", priority="urgent"),
            idempotency_key=CRITICAL_ALERT_KEY,
        )
        replay = create_alert(
            db,
            third.id,
            doctor.id,
            SafetyAlertCreate(reason_code="urgent_attention", priority="urgent"),
            idempotency_key=CRITICAL_ALERT_KEY,
        )
        assert replay.id == alert.id
        assert db.scalar(select(func.count(SafetyAlert.id))) == 1


def test_ui5_rejects_non_synthetic_patient(pg_engine) -> None:
    from backend.scripts.seed_ui5_clinical_scenarios import seed_events

    with Session(pg_engine) as db:
        patient = Patient(alias="UI5-REAL", demographics_json={})
        db.add(patient)
        db.flush()
        with pytest.raises(ValueError, match="synthetic"):
            seed_events(db, patient, "critical", datetime(2026, 10, 23, tzinfo=UTC))
        assert db.scalar(select(func.count(HistoryEvent.id))) == 0
