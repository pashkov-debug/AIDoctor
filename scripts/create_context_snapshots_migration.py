"""Сформировать миграцию поверх единственной существующей Alembic-головы."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]
REVISION = "aictx_v3_20261017"
DESTINATION = ROOT / "backend" / "alembic" / "versions" / f"{REVISION}_context_snapshots.py"

TEMPLATE = """\
\"\"\"Неизменяемые серверные снимки медицинского контекста.

Revision ID: aictx_v3_20261017
Revises: {down_revision}
\"\"\"

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "aictx_v3_20261017"
down_revision = "{down_revision}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "context_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("patient_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_id", sa.String(length=36), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("fact_count", sa.Integer(), nullable=False),
        sa.Column("payload_json", JSONB(), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
    )
    op.create_index(
        "ix_context_snapshots_patient_created",
        "context_snapshots",
        ["patient_id", "created_at"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Удаление медицинских снимков через автоматический downgrade запрещено"
    )
"""


def main() -> None:
    if not (ROOT / "alembic.ini").is_file():
        raise SystemExit("Не найден alembic.ini в корне AIDoctor")
    if DESTINATION.exists():
        if f'revision = "{REVISION}"' not in DESTINATION.read_text(encoding="utf-8"):
            raise SystemExit("Конфликт имени ревизии: файл уже существует")
        print(f"Ревизия уже создана: {DESTINATION}")
        return
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        raise SystemExit(
            f"Ожидалась одна Alembic-голова, обнаружено: {heads}. "
            "Сначала разрешите конфликт миграций."
        )
    if any(item.revision == REVISION for item in script.walk_revisions()):
        raise SystemExit("Идентификатор ревизии уже занят")
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    with DESTINATION.open("x", encoding="utf-8") as migration:
        migration.write(TEMPLATE.format(down_revision=heads[0]))
    print(f"Создана миграция: {DESTINATION.relative_to(ROOT)}")
    print(f"Родительская ревизия: {heads[0]}")


if __name__ == "__main__":
    main()
