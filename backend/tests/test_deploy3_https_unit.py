"""Контракт DEPLOY-3: публичен только TLS-прокси синтетической среды."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_TEST = ROOT / "deploy" / "compose.test.yaml"
COMPOSE_HTTPS = ROOT / "deploy" / "compose.https.yaml"
CADDY = ROOT / "deploy" / "https" / "Caddyfile"
HTTPS_DIR = ROOT / "deploy" / "https"


def _read(file: Path) -> str:
    return file.read_text(encoding="utf-8")


def test_existing_test_environment_remains_localhost_only() -> None:
    source = _read(COMPOSE_TEST)
    assert "name: aidoctor-vds-test" in source
    assert '"127.0.0.1:18080:8000"' in source
    assert "pg_synthetic:" in source
    assert "attachments_test:" in source


def test_https_compose_adds_only_a_proxy() -> None:
    source = _read(COMPOSE_HTTPS)
    assert 'profiles: ["https"]' in source
    assert "image: caddy:2.11.7-alpine" in source
    assert '"0.0.0.0:80:80/tcp"' in source
    assert '"0.0.0.0:443:443/tcp"' in source
    assert "5432:" not in source
    assert "8000:" not in source
    assert "https_caddy_data:" in source
    assert "https_caddy_config:" in source
    assert "testnet" in source


def test_caddy_proxies_existing_app_without_debug_routes() -> None:
    source = _read(CADDY)
    assert "{$AIDOCTOR_PUBLIC_DOMAIN}" in source
    assert "reverse_proxy app:8000" in source
    assert "admin off" in source
    assert "/openapi.json" in source
    assert "/api/v1/health" in source
    assert "respond @hidden 404" in source
    assert "Strict-Transport-Security" in source
    assert "tls_insecure_skip_verify" not in source


def test_enable_checks_dns_and_firewall_before_start() -> None:
    source = _read(HTTPS_DIR / "01_enable_https.sh")
    assert "getaddrinfo" in source
    assert "185.200.179.238" in source
    assert "00_firewall.sh --check" in source
    assert "config --quiet" in source
    assert "proxy adapt" in source
    assert "--force-recreate" in source
    assert "run_vds_migrations" not in source
    assert "seed_vds_synthetic" not in source
    assert "down -v" not in source


def test_stop_affects_only_https_proxy() -> None:
    source = _read(HTTPS_DIR / "03_stop_https.sh")
    assert "stop proxy" in source
    assert "down" not in source
    assert "volume rm" not in source


def test_firewall_script_preserves_ssh_access() -> None:
    source = _read(HTTPS_DIR / "00_firewall.sh")
    assert "ufw allow 22/tcp" in source
    assert "ufw --force delete allow 22" not in source
    assert "--check" in source
    assert "--apply" in source
