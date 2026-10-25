"""Контракт защищённого автодеплоя и именованной диагностики после запуска."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUTODEPLOY = ROOT / "deploy/ci/server_autodeploy.sh"
DIAGNOSE = ROOT / "deploy/ci/diagnose_failed_autodeploy.sh"


def test_failure_stage_is_logged_and_previous_image_is_restored() -> None:
    script = AUTODEPLOY.read_text(encoding="utf-8")
    assert "этап «$stage»" in script
    assert "trap rollback ERR" in script
    assert 'checkout --force --detach "$old_sha"' in script
    assert 'docker image tag "$rollback_tag" aidoctor:vds-test' in script
    assert "миграции БД автоматически НЕ откатываются" in script


def test_named_postdeploy_checks_remain_strict() -> None:
    script = AUTODEPLOY.read_text(encoding="utf-8")
    for stage in (
        "HTTP API /api/v1/health",
        "HTTP страница /app",
        "Инвариант клинических черновиков",
        "Количество синтетических пациентов",
    ):
        assert f'stage="{stage}"' in script

    assert '"status") != "ok"' in script
    assert '"environment") != "test"' in script
    assert '[[ "$app_status" != "200" ]]' in script
    assert '[[ "$draft_leaks" != "0" ]]' in script
    assert "(( patient_count < 3 ))" in script
    assert 'test "$patient_count" = 3' not in script


def test_postdeploy_checks_do_not_hang_or_change_database() -> None:
    script = AUTODEPLOY.read_text(encoding="utf-8")
    diagnose = DIAGNOSE.read_text(encoding="utf-8")
    assert "timeout --kill-after=3s 25s" in script
    assert "--max-time 5" in script
    assert "ON_ERROR_STOP=1" in script
    assert "timeout --kill-after=3s 20s" in diagnose
    for danger in ("down -v", "pg_restore", "TRUNCATE", "DROP TABLE", "seed_vds_synthetic"):
        assert danger not in script
        assert danger not in diagnose
    assert "pg_dump" in script
