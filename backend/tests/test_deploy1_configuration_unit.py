"""Проверка безопасных инвариантов конфигурации DEPLOY-1 без Docker и БД."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = (ROOT / "deploy" / "compose.yaml").read_text(encoding="utf-8")
DOCKERFILE = (ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
IGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8")
CADDY = (ROOT / "deploy" / "Caddyfile").read_text(encoding="utf-8")


def test_production_does_not_publish_postgres_or_uvicorn():
    assert "ports:" in COMPOSE
    assert COMPOSE.count("    ports:") == 1
    assert "127.0.0.1}:80:80" in COMPOSE
    assert "127.0.0.1}:443:443" in COMPOSE
    assert "APP_ENV: production" in COMPOSE
    assert 'AIDOCTOR_ALLOW_SYNTHETIC_AI_DRAFTS: "0"' in COMPOSE


def test_storage_and_secrets_are_not_baked_into_image():
    assert "!backend/app/**" in IGNORE
    assert ".env.production" not in DOCKERFILE
    assert "COPY . " not in DOCKERFILE
    assert "USER 10001:10001" in DOCKERFILE
    assert "read_only: true" in COMPOSE
    assert "postgres_data:/var/lib/postgresql/data" in COMPOSE
    assert "app_data:/opt/aidoctor/data" in COMPOSE


def test_proxy_avoids_public_debug_endpoints():
    assert "respond @debug 404" in CADDY
    assert "reverse_proxy app:8000" in CADDY
    assert "{$AIDOCTOR_DOMAIN}" in CADDY


def test_preflight_rejects_empty_secret_and_public_localhost(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "deploy_preflight", ROOT / "deploy" / "preflight.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    cfg = tmp_path / ".env.production"
    cfg.write_text("DB_PASSWORD=\nAIDOCTOR_DOMAIN=localhost\nBIND_ADDRESS=127.0.0.1\n")
    cfg.chmod(0o600)
    assert any("DB_PASSWORD" in error for error in module.check_configuration(cfg))

    cfg.write_text(
        "DB_PASSWORD=abcdefghijklmnopqrstuvwxyz0123456789\n"
        "AIDOCTOR_DOMAIN=localhost\nBIND_ADDRESS=0.0.0.0\n"
    )
    assert any("Публичная публикация" in error for error in module.check_configuration(cfg))
