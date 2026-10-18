"""Адаптер доставки только в PostgreSQL inbox, без внешних вызовов.

Без включения CLI он не выполняется. Отсутствие маршрута — ошибка,
а не фиктивное подтверждение доставки.
"""

import hashlib
from collections.abc import Callable

from app.db.base import new_uuid, utc_now
from app.models.safety_alert import SafetyAlert
from app.models.safety_in_app_notification import SafetyInAppNotification
from app.models.safety_outbox import SafetyOutbox
from app.services.safety_notification_routes import eligible_routes
from app.workers.safety_outbox import (
    DeliveryEnvelope,
    DeliveryReceipt,
    TransportFailure,
    TransportNotConfigured,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

SessionFactory = Callable[[], Session]


class InAppTransport:
    """Транзакционная локальная доставка в подтверждённые in_app-маршруты.

    UNIQUE(outbox_id, recipient_user_id) устраняет повторную запись,
    если процесс упал между commit inbox и mark_delivered Outbox.
    """

    def __init__(self, session_factory: SessionFactory, *, enabled: bool = False) -> None:
        if enabled is not True:
            raise TransportNotConfigured("Внутренняя доставка не разрешена")
        self._session_factory = session_factory

    def send(self, envelope: DeliveryEnvelope) -> DeliveryReceipt:
        with self._session_factory() as session:
            try:
                item = session.scalar(
                    select(SafetyOutbox)
                    .where(SafetyOutbox.id == envelope.outbox_id)
                    .with_for_update()
                )
                if (
                    item is None
                    or item.alert_id != envelope.alert_id
                    or item.event_type != "created"
                    or envelope.event_type != "created"
                    or item.status != "processing"
                    or item.attempt_count != envelope.attempt_number
                    or item.lease_expires_at is None
                    or item.lease_expires_at <= utc_now()
                ):
                    raise TransportFailure("route_unavailable")

                patient_id = session.scalar(
                    select(SafetyAlert.patient_id).where(
                        SafetyAlert.id == envelope.alert_id
                    )
                )
                if patient_id is None:
                    raise TransportFailure("route_unavailable")

                routes = eligible_routes(session, patient_id=patient_id, for_delivery=True)
                if not routes:
                    raise TransportFailure("route_unavailable")

                for route in routes:
                    # Идемпотентно даже при повторном запуске после потери receipt.
                    session.execute(
                        pg_insert(SafetyInAppNotification)
                        .values(
                            id=new_uuid(),
                            created_at=utc_now(),
                            outbox_id=item.id,
                            alert_id=item.alert_id,
                            patient_id=patient_id,
                            recipient_user_id=route.recipient_user_id,
                            route_id=route.route_id,
                        )
                        .on_conflict_do_nothing(
                            constraint="uq_safety_in_app_outbox_recipient"
                        )
                    )
                session.commit()
            except Exception:
                session.rollback()
                raise

        # Детерминированный технический receipt, НЕ доказательство прочтения.
        digest = hashlib.sha256(
            f"in_app:v1:{envelope.outbox_id}".encode("ascii")
        ).hexdigest()
        return DeliveryReceipt(confirmation_id=f"in_app:{digest}")


def list_own_inbox(
    session: Session, *, recipient_user_id: str, limit: int = 50
) -> list[SafetyInAppNotification]:
    """Только уведомления врача с действующей связью с НЕудалённым пациентом."""
    if not 1 <= limit <= 100:
        raise ValueError("limit должен быть от 1 до 100")

    from app.models.access import DoctorPatient
    from app.models.patient import Patient

    return list(
        session.scalars(
            select(SafetyInAppNotification)
            .join(
                DoctorPatient,
                (DoctorPatient.doctor_id == SafetyInAppNotification.recipient_user_id)
                & (DoctorPatient.patient_id == SafetyInAppNotification.patient_id),
            )
            .join(Patient, Patient.id == SafetyInAppNotification.patient_id)
            .where(
                SafetyInAppNotification.recipient_user_id == recipient_user_id,
                Patient.deleted_at.is_(None),
            )
            .order_by(
                SafetyInAppNotification.created_at.desc(),
                SafetyInAppNotification.id.desc(),
            )
            .limit(limit)
        ).all()
    )
