"""Создать учётную запись через CLI. Пароль вводится без отображения."""

import argparse
import getpass

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.access import User
from sqlalchemy import select


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("role", choices=["admin", "doctor", "patient"])
    args = parser.parse_args()
    password = getpass.getpass("Пароль (минимум 12 символов): ")
    confirm = getpass.getpass("Подтверждение: ")
    if password != confirm:
        raise SystemExit("Пароли не совпадают")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == args.username)):
            raise SystemExit("Пользователь уже существует")
        user = User(username=args.username, role=args.role, password_hash=hash_password(password))
        db.add(user)
        db.commit()
        print(f"Создан пользователь {user.username}; id={user.id}")


if __name__ == "__main__":
    main()
