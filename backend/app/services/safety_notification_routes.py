"""Политика маршрутизации 5.5: только собственная in_app-учётная запись врача.

Запись настроек и аудит — одна транзакция. Ни почты, ни телефона, ни отправки.
"""

from dataclasses import dataclass

from app.db.base import new_uuid, utc_now
from app.models.access import DoctorPatient, User
from app.models.patient import Patient
from app.models.safety_notification_route import (
    SafetyNotificationRoute,
    SafetyNotificationRouteEvent,
)
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session


class RouteAccessDenied(Exception):
    """Нет действующей связи врача с пациентом или неверная роль."""


@dataclass(frozen=True)
class EligibleRoute:
    """Только идентификаторы для будущего адаптера, без PII и медданных."""

    route_id: str
    recipient_user_id: str
    channel: str


def _require_link(session: Session, patient_id: str, actor_id: str) -> None:
    valid = session.scalar(
        select(DoctorPatient.id)
        .join(User, User.id == DoctorPatient.doctor_id)
        .join(Patient, Patient.id == DoctorPatient.patient_id)
        .where(
            DoctorPatient.patient_id == patient_id,
            DoctorPatient.doctor_id == actor_id,
            User.role == "doctor",
            Patient.deleted_at.is_(None),
        )
    )
    if valid is None:
        raise RouteAccessDenied


def get_own_route(
    session: Session, *, patient_id: str, actor_id: str
) -> SafetyNotificationRoute | None:
    _require_link(session, patient_id, actor_id)
    return session.scalar(
        select(SafetyNotificationRoute).where(
            SafetyNotificationRoute.patient_id == patient_id,
            SafetyNotificationRoute.recipient_user_id == actor_id,
            SafetyNotificationRoute.channel == "in_app",
        )
    )


def configure_own_route(
    session: Session, *, patient_id: str, actor_id: str, enabled: bool
) -> SafetyNotificationRoute:
    """Повтор неизменного значения не добавляет аудит; коммит принадлежит сервису.

    Согласие подтверждено авторизованным владельцем in_app-аккаунта при
    включении. Это НЕ подтверждение email/телефона и НЕ разрешение отправлять.
    """
    if type(enabled) is not bool:
        raise ValueError("enabled должен быть bool")
    try:
        _require_link(session, patient_id, actor_id)
        now = utc_now()
        table = SafetyNotificationRoute
        stmt = (
            pg_insert(table)
            .values(
                id=new_uuid(),
                created_at=now,
                patient_id=patient_id,
                recipient_user_id=actor_id,
                channel="in_app",
                enabled=enabled,
                confirmed_at=now if enabled else None,
            )
        )
        updated_id = session.scalar(
            stmt.on_conflict_do_update(
                constraint="uq_safety_notification_routes_scope",
                set_={
                    "enabled": stmt.excluded.enabled,
                    "confirmed_at": func.coalesce(
                        table.confirmed_at, stmt.excluded.confirmed_at
                    ),
                },
                where=table.enabled.is_distinct_from(stmt.excluded.enabled),
            ).returning(table.id)
        )
        if updated_id is not None:
            session.add(
                SafetyNotificationRouteEvent(
                    route_id=updated_id,
                    actor_id=actor_id,
                    event_type="enabled" if enabled else "disabled",
                )
            )
        session.commit()
        result = session.scalar(
            select(table).where(
                table.patient_id == patient_id,
                table.recipient_user_id == actor_id,
                table.channel == "in_app",
            )
        )
        if result is None:
            raise RuntimeError("Невозможно прочитать сохранённый маршрут")
        return result
    except Exception:
        session.rollback()
        raise


def eligible_routes(
    session: Session, *, patient_id: str, for_delivery: bool = False
) -> tuple[EligibleRoute, ...]:
    """Fail-closed: маршрут, связь и пациент должны быть действующими.

    Режим for_delivery удерживает блокировки до commit/rollback адаптера:
    отключение маршрута и отзыв доступа не обгоняют создание inbox.
    """
    stmt = (
        select(SafetyNotificationRoute)
        .join(
            DoctorPatient,
            (DoctorPatient.doctor_id == SafetyNotificationRoute.recipient_user_id)
            & (DoctorPatient.patient_id == SafetyNotificationRoute.patient_id),
        )
        .join(User, User.id == SafetyNotificationRoute.recipient_user_id)
        .join(Patient, Patient.id == SafetyNotificationRoute.patient_id)
        .where(
            SafetyNotificationRoute.patient_id == patient_id,
            SafetyNotificationRoute.enabled.is_(True),
            SafetyNotificationRoute.confirmed_at.is_not(None),
            SafetyNotificationRoute.channel == "in_app",
            User.role == "doctor",
            Patient.deleted_at.is_(None),
        )
        .order_by(SafetyNotificationRoute.id)
    )
    if for_delivery:
        stmt = stmt.with_for_update(
            of=(SafetyNotificationRoute, DoctorPatient, User, Patient)
        )
    records = session.scalars(stmt).all()
    return tuple(
        EligibleRoute(
            route_id=route.id,
            recipient_user_id=route.recipient_user_id,
            channel=route.channel,
        )
        for route in records
    )
