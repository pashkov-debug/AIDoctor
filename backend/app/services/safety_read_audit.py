"""Записывает факт разрешённого чтения до выдачи HTTP-ответа.

При сбое БД доступ fail-closed: ответ с данными не возвращается.
"""

from typing import Literal

from app.models.safety_read_audit import SafetyReadAudit
from sqlalchemy.orm import Session

ReadScope = Literal["alerts_list", "route_read", "inbox_list", "followups_list"]
_PATIENT_SCOPES = frozenset({"alerts_list", "route_read"})
_ALL_SCOPES = frozenset((*_PATIENT_SCOPES, "inbox_list", "followups_list"))


def record_safety_read(
    session: Session,
    *,
    actor_id: str,
    scope: ReadScope,
    returned_count: int,
    patient_id: str | None = None,
) -> None:
    """Только для авторизованного успешного GET; commit владеет аудит-сервис.

    Авторизацию выполнять ДО вызова. Не записывать запрещённые запросы
    без отдельного операционного security-лога и его политики хранения.
    """
    if scope not in _ALL_SCOPES:
        raise ValueError("Неизвестный тип чтения")
    if not isinstance(actor_id, str) or not actor_id.strip():
        raise ValueError("actor_id обязателен")
    if type(returned_count) is not int or not 0 <= returned_count <= 100:
        raise ValueError("returned_count должен быть числом 0..100")
    if (patient_id is not None) != (scope in _PATIENT_SCOPES):
        raise ValueError("Неверная область patient_id")
    if patient_id is not None and (
        not isinstance(patient_id, str) or not patient_id.strip()
    ):
        raise ValueError("patient_id обязателен для чтения пациента")

    try:
        session.add(
            SafetyReadAudit(
                actor_id=actor_id,
                patient_id=patient_id,
                scope=scope,
                returned_count=returned_count,
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
