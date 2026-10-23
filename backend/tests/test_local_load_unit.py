"""Безопасность и статистика локального измерителя, без PostgreSQL."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from scripts.load_test_local import (
    LocalHttp,
    Observation,
    build_url,
    parse_levels,
    percentile,
    preflight_app,
    preflight_mock,
    stage,
    summarize,
)


def test_levels_validation():
    assert parse_levels("2,5,10") == [2, 5, 10]
    for value in ("0", "200", "10,5", "2,2", "a", ""):
        with pytest.raises(ValueError):
            parse_levels(value)


def test_percentiles_and_empty_samples():
    assert percentile([], 0.95) is None
    assert percentile([1, 2, 3, 4, 5], 0.50) == 3
    assert percentile([1, 2, 3, 4, 5], 0.95) == 5
    result = summarize(
        [
            Observation("doctor", 20, True),
            Observation("doctor", 40, True),
            Observation("patient", 50, False, "http_503"),
        ],
        duration_s=2,
        users=3,
    )
    assert result["requests"] == 3
    assert result["errors"] == 1
    assert result["rps"] == 1.5
    assert result["p95_ms"] == 40
    assert result["by_role"]["patient"]["errors"] == 1


def test_local_only():
    assert build_url(8000) == "http://127.0.0.1:8000"
    with pytest.raises(ValueError):
        build_url(80)
    with pytest.raises(ValueError):
        LocalHttp("http://example.com")
    with pytest.raises(ValueError):
        LocalHttp("http://localhost:8000")
    client = LocalHttp("http://127.0.0.1:8000")
    with pytest.raises(ValueError):
        client.get("//example.com/path")


class Stub(BaseHTTPRequestHandler):
    environment = "local"

    def log_message(self, *args):
        return

    def _json(self, payload: dict, status=200):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/v1/health":
            return self._json({"status": "ok", "environment": self.environment})
        if self.path == "/api/v1/auth/me":
            token = self.headers.get("Authorization")
            role = "doctor" if token == "Bearer doctor_token" else "patient"
            return self._json({"role": role})
        if self.path == "/api/v1/patients":
            return self._json(
                {
                    "items": [
                        {"id": "syn1", "demographics": {"synthetic": True}},
                    ]
                }
            )
        if self.path == "/api/v1/patients/me/portal":
            return self._json({"patient_id": "syn1"})
        if self.path.startswith("/api/v1/"):
            return self._json([])
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path != "/api/v1/auth/login":
            return self._json({}, 404)
        count = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(count))
        token = "doctor_token" if body["username"] == "doctor" else "patient_token"
        return self._json({"access_token": token})


@pytest.fixture
def stub_server(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr("getpass.getpass", lambda *_: "long-test-password")
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_synthetic_local_preflight_and_read_only_load(stub_server):
    base = f"http://127.0.0.1:{stub_server.server_port}"
    client = LocalHttp(base)
    plan = preflight_app(client, "doctor", "patient")
    assert plan["paths"]["doctor"]
    result = stage(
        client,
        users=2,
        duration=0.1,
        doctor_share=0.5,
        think_ms=20,
        mode="app",
        plan=plan,
    )
    assert result["requests"] > 0
    assert result["errors"] == 0
    assert set(result["by_role"]) == {"doctor", "patient"}


def test_production_is_forbidden(stub_server):
    class ProductionStub(Stub):
        environment = "production"

    stub_server.RequestHandlerClass = ProductionStub
    client = LocalHttp(f"http://127.0.0.1:{stub_server.server_port}")
    with pytest.raises(RuntimeError, match="APP_ENV"):
        preflight_app(client, "doctor", "patient")


def test_mock_identity_validation(stub_server):
    client = LocalHttp(f"http://127.0.0.1:{stub_server.server_port}")
    with pytest.raises(RuntimeError, match="AI MOCK"):
        preflight_mock(client)
