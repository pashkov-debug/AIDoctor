"""5.7: административный контроль непросмотренных ручных сигналов.

Не отправляет сообщения, не вычисляет клинический риск и не меняет SafetyAlert.
Блокировка сигнала защищает от гонки с ACK; блокировка маршрута/врача —
от отключения маршрута и параллельного превышения лимита.
"""

from datetime import UTC, datetime, timedelta

from app.db.base import new_uuid, utc_now
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from app.models.safety_alert import SafetyAlert
from app.models.safety_followup import SafetyFollowup
from app.models.safety_notification_route import SafetyNotificationRoute
from app.services.safety_notification_routes import eligible_routes
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

FOLLOWUP_AFTER_HOURS = 24
FOLLOWUP_WINDOW_HOURS = 24
MAX_FOLLOWUPS_PER_DOCTOR_WINDOW = 5
SCAN_LIMIT = 100


def _moment(value: datetime | None) -> datetime:
    result = value if value is not None else utc_now()
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("now должен содержать часовой пояс")
    return result.astimezone(UTC)


def create_one_due_followup(session: Session, *, now: datetime | None = None) -> str:
    """Одно сохранённое событие максимум; возвращает created или empty.

    Только маршруты in_app с действующим opt-in; ни одна запись Inbox
    или Outbox этим методом не создаётся. Session/commit принадлежит сервису.
    """
    moment = _moment(now)
    cutoff = moment - timedelta(hours=FOLLOWUP_AFTER_HOURS)
    window_start = moment - timedelta(hours=FOLLOWUP_WINDOW_HOURS)
    route = SafetyNotificationRoute
    followup = SafetyFollowup

    # Отбираем только ещё не назначенные пары сигнал/врач, чтобы повторные
    # запуски не застревали на уже обработанных сигналах.
    candidate_query = (
        select(SafetyAlert.id)
        .join(Patient, Patient.id == SafetyAlert.patient_id)
        .join(route, route.patient_id == SafetyAlert.patient_id)
        .join(
            DoctorPatient,
            (DoctorPatient.patient_id == SafetyAlert.patient_id)
            & (DoctorPatient.doctor_id == route.recipient_user_id),
        )
        .join(User, User.id == route.recipient_user_id)
        .outerjoin(
            followup,
            (followup.alert_id == SafetyAlert.id)
            & (followup.recipient_user_id == route.recipient_user_id),
        )
        .where(
            SafetyAlert.status == "open",
            SafetyAlert.created_at <= cutoff,
            Patient.deleted_at.is_(None),
            route.enabled.is_(True),
            route.confirmed_at.is_not(None),
            route.channel == "in_app",
            User.role == "doctor",
            followup.id.is_(None),
        )
        .order_by(SafetyAlert.created_at, SafetyAlert.id)
        .limit(SCAN_LIMIT)
    )

    try:
        # Первичная выборка без блокировок; блокируем и повторно проверяем
        # только один сигнал за раз, не задерживая ACK для остальных.
        alert_ids = dict.fromkeys(session.scalars(candidate_query).all())
        if not alert_ids:
            session.commit()
            return "empty"
        for alert_id in alert_ids:
            alert = session.scalar(
                select(SafetyAlert)
                .where(
                    SafetyAlert.id == alert_id,
                    SafetyAlert.status == "open",
                    SafetyAlert.created_at <= cutoff,
                )
                .with_for_update(skip_locked=True)
            )
            if alert is None:
                session.commit()
                continue
            # Блокирует подтверждённый маршрут, DoctorPatient и User.
            # Все решения принимаются в той же транзакции, что INSERT.
            routes = eligible_routes(session, patient_id=alert.patient_id, for_delivery=True)
            for recipient in routes:
                exists = session.scalar(
                    select(followup.id).where(
                        followup.alert_id == alert.id,
                        followup.recipient_user_id == recipient.recipient_user_id,
                    )
                )
                if exists is not None:
                    continue
                count = session.scalar(
                    select(func.count(followup.id)).where(
                        followup.recipient_user_id == recipient.recipient_user_id,
                        followup.created_at > window_start,
                    )
                )
                if count is None or count >= MAX_FOLLOWUPS_PER_DOCTOR_WINDOW:
                    continue
                created_id = session.scalar(
                    pg_insert(followup)
                    .values(
                        id=new_uuid(),
                        created_at=moment,
                        alert_id=alert.id,
                        patient_id=alert.patient_id,
                        recipient_user_id=recipient.recipient_user_id,
                        route_id=recipient.route_id,
                    )
                    .on_conflict_do_nothing(constraint="uq_safety_followups_alert_recipient")
                    .returning(followup.id)
                )
                if created_id is not None:
                    session.commit()
                    return "created"
            # Не держим блокировку ACK/маршрута для последующих кандидатов.
            session.commit()
        return "empty"
    except Exception:
        session.rollback()
        raise


def list_own_open_followups(
    session: Session, *, recipient_user_id: str, limit: int = 50
) -> list[SafetyFollowup]:
    """Виден только открытый сигнал, действующая связь и разрешённый маршрут."""
    if not 1 <= limit <= 100:
        raise ValueError("limit должен быть от 1 до 100")
    return list(
        session.scalars(
            select(SafetyFollowup)
            .join(SafetyAlert, SafetyAlert.id == SafetyFollowup.alert_id)
            .join(Patient, Patient.id == SafetyFollowup.patient_id)
            .join(
                DoctorPatient,
                (DoctorPatient.patient_id == SafetyFollowup.patient_id)
                & (DoctorPatient.doctor_id == SafetyFollowup.recipient_user_id),
            )
            .join(User, User.id == SafetyFollowup.recipient_user_id)
            .join(
                SafetyNotificationRoute,
                SafetyNotificationRoute.id == SafetyFollowup.route_id,
            )
            .where(
                SafetyNotificationRoute.patient_id == SafetyFollowup.patient_id,
                SafetyNotificationRoute.recipient_user_id == SafetyFollowup.recipient_user_id,
                SafetyFollowup.recipient_user_id == recipient_user_id,
                SafetyAlert.status == "open",
                Patient.deleted_at.is_(None),
                User.role == "doctor",
                SafetyNotificationRoute.enabled.is_(True),
                SafetyNotificationRoute.confirmed_at.is_not(None),
            )
            .order_by(SafetyFollowup.created_at.desc(), SafetyFollowup.id.desc())
            .limit(limit)
        ).all()
    )
