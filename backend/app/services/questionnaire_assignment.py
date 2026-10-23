"""UI-3B: назначение, завершение и сигнал риска одной транзакцией."""

from app.clinical.demo_test_catalog import CATALOG, definition, score
from app.db.base import utc_now
from app.models.patient import Patient
from app.models.questionnaire_assignment import (
    QuestionnaireAssignment as Assignment,
)
from app.models.questionnaire_assignment import (
    QuestionnaireAssignmentAudit as Audit,
)
from app.models.questionnaire_assignment import (
    QuestionnaireSubmission as Submission,
)
from app.models.safety_alert import SafetyAlert, SafetyAlertEvent
from app.schemas.questionnaire_assignment import (
    AssignDemoTest,
    CancelDemoTest,
    DoctorTestAssignmentRead,
    SubmitDemoTest,
    TestAssignmentRead,
    TestResultRead,
)
from app.services.safety_outbox import enqueue_alert_created
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def catalog() -> list[dict]:
    return [definition(key).to_catalog() for key in sorted(CATALOG)]


def _result(item: Submission | None) -> TestResultRead | None:
    if item is None:
        return None
    return TestResultRead(
        answers=item.answers_json,
        total_score=item.total_score,
        critical_flag=item.critical_flag,
        submitted_at=item.created_at,
    )


def _read(db: Session, record: Assignment, *, doctor: bool = False):
    result = db.scalar(select(Submission).where(Submission.assignment_id == record.id))
    fields = dict(
        id=record.id,
        test_id=record.test_id,
        test_version=record.test_version,
        title=definition(record.test_id).title,
        status=record.status,
        revision=record.revision,
        created_at=record.created_at,
        completed_at=record.completed_at,
        result=_result(result),
    )
    if doctor:
        return DoctorTestAssignmentRead(
            **fields,
            patient_id=record.patient_id,
            assigned_by_id=record.assigned_by_id,
            cancelled_at=record.cancelled_at,
            cancel_reason=record.cancel_reason,
            alert_id=result.alert_id if result else None,
        )
    return TestAssignmentRead(**fields)


def _audit(
    db: Session, record: Assignment, actor: str, action: str, details: dict | None = None
) -> None:
    snapshot = dict(
        patient_id=record.patient_id,
        test_id=record.test_id,
        test_version=record.test_version,
        status=record.status,
        revision=record.revision,
        details=details or {},
    )
    db.add(
        Audit(
            assignment_id=record.id,
            actor_id=actor,
            action=action,
            revision=record.revision,
            snapshot_json=snapshot,
        )
    )


def _lock(db: Session, assignment_id: str, patient_id: str) -> Assignment:
    record = db.scalar(
        select(Assignment)
        .where(Assignment.id == assignment_id, Assignment.patient_id == patient_id)
        .with_for_update()
    )
    if record is None:
        raise HTTPException(404, "Назначение теста не найдено")
    return record


def assign(
    db: Session, patient_id: str, actor_id: str, data: AssignDemoTest
) -> DoctorTestAssignmentRead:
    chosen = definition(data.test_id)
    key = str(data.request_key)
    existing = db.scalar(
        select(Assignment).where(
            Assignment.assigned_by_id == actor_id,
            Assignment.request_key == key,
        )
    )
    if existing is not None:
        if existing.patient_id != patient_id or existing.test_id != data.test_id:
            raise HTTPException(409, "Ключ повторно использован для другого теста")
        return _read(db, existing, doctor=True)

    entry = Assignment(
        patient_id=patient_id,
        assigned_by_id=actor_id,
        request_key=key,
        test_id=chosen.test_id,
        test_version=chosen.version,
        status="assigned",
        revision=1,
    )
    db.add(entry)
    try:
        db.flush()
        _audit(db, entry, actor_id, "assigned")
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        replay = db.scalar(
            select(Assignment).where(
                Assignment.assigned_by_id == actor_id,
                Assignment.request_key == key,
            )
        )
        if replay and replay.patient_id == patient_id and replay.test_id == data.test_id:
            return _read(db, replay, doctor=True)
        raise HTTPException(409, "Конфликт ключа создания") from exc
    except Exception:
        db.rollback()
        raise
    return _read(db, entry, doctor=True)


def list_doctor(db: Session, patient_id: str) -> list[DoctorTestAssignmentRead]:
    items = db.scalars(
        select(Assignment)
        .where(
            Assignment.patient_id == patient_id,
        )
        .order_by(Assignment.created_at.desc(), Assignment.id.desc())
        .limit(500)
    ).all()
    return [_read(db, item, doctor=True) for item in items]


def own_patient_id(db: Session, user_id: str) -> str:
    patient_id = db.scalar(
        select(Patient.id).where(
            Patient.user_id == user_id,
            Patient.deleted_at.is_(None),
        )
    )
    if not patient_id:
        raise HTTPException(404, "Карточка пациента не привязана")
    return patient_id


def list_own(db: Session, user_id: str) -> list[TestAssignmentRead]:
    patient_id = own_patient_id(db, user_id)
    items = db.scalars(
        select(Assignment)
        .where(
            Assignment.patient_id == patient_id,
            Assignment.status != "cancelled",
        )
        .order_by(Assignment.created_at.desc(), Assignment.id.desc())
        .limit(500)
    ).all()
    return [_read(db, item) for item in items]


def cancel(
    db: Session, patient_id: str, assignment_id: str, actor_id: str, data: CancelDemoTest
) -> DoctorTestAssignmentRead:
    record = _lock(db, assignment_id, patient_id)
    if record.status != "assigned" or record.revision != data.expected_revision:
        raise HTTPException(409, "Тест уже завершён, отменён или изменился")
    record.status = "cancelled"
    record.revision += 1
    record.cancelled_at = utc_now()
    record.cancel_reason = data.reason
    _audit(db, record, actor_id, "cancelled", {"reason": data.reason})
    db.commit()
    return _read(db, record, doctor=True)


def submit(
    db: Session, user_id: str, assignment_id: str, data: SubmitDemoTest
) -> TestAssignmentRead:
    patient_id = own_patient_id(db, user_id)
    record = _lock(db, assignment_id, patient_id)
    if record.status == "completed":
        saved = db.scalar(
            select(Submission).where(
                Submission.assignment_id == record.id,
            )
        )
        if (
            saved
            and saved.answers_json == data.answers
            and (data.expected_revision == record.revision - 1)
        ):
            return _read(db, record)
        raise HTTPException(409, "Тест уже завершён; ответы не изменяются")
    if record.status != "assigned" or record.revision != data.expected_revision:
        raise HTTPException(409, "Назначение отменено или изменилось")
    try:
        total, critical = score(record.test_id, record.test_version, data.answers)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc

    # В существующей службе create_alert() собственный commit, поэтому
    # повторяем атомарную запись Alert+Event+Outbox в ТЕКУЩЕЙ транзакции.
    # Так невозможна завершённая анкета без обязательного сигнала.
    alert_id = None
    try:
        if critical:
            alert = SafetyAlert(
                patient_id=patient_id,
                created_by_id=user_id,
                reason_code="urgent_attention",
                priority="urgent",
                status="open",
            )
            db.add(alert)
            db.flush()
            alert_id = alert.id
            db.add(
                SafetyAlertEvent(
                    alert_id=alert.id,
                    actor_id=user_id,
                    event_type="created",
                )
            )
            enqueue_alert_created(db, alert.id)

        submission = Submission(
            assignment_id=record.id,
            patient_id=patient_id,
            answers_json=list(data.answers),
            total_score=total,
            critical_flag=critical,
            alert_id=alert_id,
        )
        db.add(submission)
        record.status = "completed"
        record.revision += 1
        record.completed_at = utc_now()
        db.flush()
        _audit(
            db,
            record,
            user_id,
            "completed",
            {
                "submission_id": submission.id,
                "score": total,
                "critical": critical,
                "alert_id": alert_id,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _read(db, record)
