"""Единая точка добавления аудит-событий административных команд."""

from app.models.admin_audit import AdminAuditEvent
from sqlalchemy.orm import Session


def record_admin_action(
    db: Session,
    *,
    actor_id: str,
    action: str,
    target_id: str,
    details: dict | None = None,
) -> None:
    # Вызывать в той же транзакции, что и изменение данных.
    db.add(
        AdminAuditEvent(
            actor_id=actor_id,
            action=action,
            target_id=target_id,
            details_json=details or {},
        )
    )
