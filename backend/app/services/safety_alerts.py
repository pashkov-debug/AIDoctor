"""Транзакции сигналов; подтверждение атомарно и идемпотентно в PostgreSQL."""

from app.db.base import utc_now
from app.models.safety_alert import SafetyAlert, SafetyAlertEvent
from app.schemas.safety_alert import SafetyAlertCreate
from sqlalchemy import select, update
from sqlalchemy.orm import Session


class AlertNotFoundError(Exception):
    """Сигнал отсутствует у данного пациента."""


def list_alerts(session: Session, patient_id: str) -> list[SafetyAlert]:
    return list(
        session.scalars(
            select(SafetyAlert)
            .where(SafetyAlert.patient_id == patient_id)
            .order_by(SafetyAlert.created_at.desc(), SafetyAlert.id.desc())
            .limit(100)
        ).all()
    )


def create_alert(
    session: Session, patient_id: str, actor_id: str, data: SafetyAlertCreate
) -> SafetyAlert:
    try:
        alert = SafetyAlert(
            patient_id=patient_id,
            created_by_id=actor_id,
            reason_code=data.reason_code,
            priority=data.priority,
            status="open",
        )
        session.add(alert)
        session.flush()
        session.add(
            SafetyAlertEvent(
                alert_id=alert.id, actor_id=actor_id, event_type="created"
            )
        )
        session.commit()
        session.refresh(alert)
        return alert
    except Exception:
        session.rollback()
        raise


def acknowledge_alert(
    session: Session, patient_id: str, alert_id: str, actor_id: str
) -> SafetyAlert:
    alert = session.scalar(
        select(SafetyAlert).where(
            SafetyAlert.id == alert_id, SafetyAlert.patient_id == patient_id
        )
    )
    if alert is None:
        raise AlertNotFoundError

    if alert.status == "acknowledged":
        return alert

    try:
        acknowledged_id = session.scalar(
            update(SafetyAlert)
            .where(
                SafetyAlert.id == alert_id,
                SafetyAlert.patient_id == patient_id,
                SafetyAlert.status == "open",
            )
            .values(
                status="acknowledged",
                acknowledged_by_id=actor_id,
                acknowledged_at=utc_now(),
            )
            .returning(SafetyAlert.id)
        )
        if acknowledged_id is not None:
            session.add(
                SafetyAlertEvent(
                    alert_id=alert_id, actor_id=actor_id, event_type="acknowledged"
                )
            )
        session.commit()
        refreshed = session.get(SafetyAlert, alert_id)
        if refreshed is None:
            raise AlertNotFoundError
        return refreshed
    except Exception:
        session.rollback()
        raise
