"""Однократная выдача и отзыв персонального Site-ключа врача.

Запуск в контейнере приложения: python -m backend.scripts.site_doctor_keys ...
Ключ показывается только один раз. Храните его в Secret Manager Site.
"""

import argparse

from app.db.session import SessionLocal
from app.models.access import User
from app.models.site_doctor_credential import SiteDoctorCredential
from app.services.site_doctor_access import (
    expiry_from_now,
    hash_site_key,
    new_site_key,
    site_enabled,
)
from sqlalchemy import select


def main() -> int:
    parser = argparse.ArgumentParser(description="Управление персональным ключом Site")
    parser.add_argument("action", choices=("issue", "revoke"))
    parser.add_argument("username", help="Логин врача")
    args = parser.parse_args()
    if not site_enabled():
        parser.error("Site Multi Doctor должен быть явно включён в TEST")
    with SessionLocal() as db:
        doctor = db.scalar(
            select(User).where(User.username == args.username, User.role == "doctor")
        )
        if doctor is None:
            parser.error("Врач с таким логином отсутствует")

        # Перед выпуском нового ключа предыдущие отзываются.
        rows = db.scalars(
            select(SiteDoctorCredential).where(
                SiteDoctorCredential.doctor_id == doctor.id,
                SiteDoctorCredential.enabled.is_(True),
            )
        ).all()
        for row in rows:
            row.enabled = False

        secret = None
        if args.action == "issue":
            secret = new_site_key()
            db.add(
                SiteDoctorCredential(
                    doctor_id=doctor.id,
                    key_hash=hash_site_key(secret),
                    expires_at=expiry_from_now(),
                    enabled=True,
                )
            )
        db.commit()

    print(f"Действие {args.action} для врача {args.username} выполнено.")
    if secret is not None:
        print("Скопируйте секрет в защищённое хранилище Site (только один раз):")
        print(secret)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
