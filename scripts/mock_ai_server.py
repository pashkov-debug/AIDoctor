"""Локальный HTTP-имитатор AI-сервиса: только проверка доставки, без LLM.

Запуск: python -m scripts.mock_ai_server
Прослушивание только 127.0.0.1. Не принимает клинический контекст.
"""

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import UUID

REQUEST_SCHEMA = "aidoctor.mock_connection.v1"
RESPONSE_SCHEMA = "aidoctor.mock_receipt.v1"
MAX_REQUEST_BYTES = 4096
REQUIRED_FIELDS = frozenset({
    "schema_version",
    "request_id",
    "context_sha256",
    "context_schema",
    "synthetic_confirmed",
    "approved_count",
    "draft_count",
})


def validate_envelope(value: object) -> dict:
    """Проверить, что сервису не отправлены медицинские данные."""
    if not isinstance(value, dict) or set(value) != REQUIRED_FIELDS:
        raise ValueError("Допустимы только технические поля протокола")
    if value["schema_version"] != REQUEST_SCHEMA:
        raise ValueError("Неизвестная версия протокола")
    if value["context_schema"] != "ai_agent_context.v1":
        raise ValueError("Неверная версия контекста")
    if value["synthetic_confirmed"] is not True:
        raise ValueError("Разрешены только синтетические пациенты")
    try:
        UUID(str(value["request_id"]))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Некорректный ID запроса") from exc
    checksum = value["context_sha256"]
    if not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise ValueError("Неверная контрольная сумма")
    for name in ("approved_count", "draft_count"):
        count = value[name]
        if type(count) is not int or not (0 <= count <= 100):
            raise ValueError("Некорректное количество назначений")
    return value


class MockHandler(BaseHTTPRequestHandler):
    server_version = "AIDoctorMock/1"
    sys_version = ""

    def log_message(self, _format: str, *args: object) -> None:
        # Не сохраняем тело запроса, имена пациентов и токены.
        return

    def send_json(self, status: int, payload: dict) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        if self.path == "/health":
            self.send_json(200, {
                "status": "ready",
                "service": "local_ai_mock",
                "llm_connected": False,
            })
        else:
            self.send_json(404, {"error": "Маршрут не найден"})

    def do_POST(self) -> None:
        if self.path != "/v1/simulate":
            self.send_json(404, {"error": "Маршрут не найден"})
            return
        length_header = self.headers.get("Content-Length", "")
        if not length_header.isdecimal() or not (1 <= int(length_header) <= MAX_REQUEST_BYTES):
            self.send_json(413, {"error": "Неверная длина запроса"})
            return
        content_type = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if content_type != "application/json":
            self.send_json(415, {"error": "Ожидается JSON"})
            return
        try:
            payload = json.loads(
                self.rfile.read(int(length_header)).decode("utf-8"),
                parse_constant=lambda _x: (_ for _ in ()).throw(
                    ValueError("NaN/Infinity запрещены")
                ),
            )
            request = validate_envelope(payload)
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            self.send_json(422, {"error": "Некорректный технический запрос"})
            return
        self.send_json(200, {
            "schema_version": RESPONSE_SCHEMA,
            "service": "local_ai_mock",
            "origin": "synthetic_connection_test",
            "request_id": request["request_id"],
            "received_context_sha256": request["context_sha256"],
            "approved_count": request["approved_count"],
            "draft_count": request["draft_count"],
            "delivery_confirmed": True,
            "llm_connected": False,
            "analysis_performed": False,
            "recommendations": [],
            "message": "Связь проверена. Анализ AI не выполнялся.",
        })


def main() -> None:
    parser = argparse.ArgumentParser(description="Локальный имитатор AI без LLM")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Порт должен быть от 1024 до 65535")
    with ThreadingHTTPServer(("127.0.0.1", args.port), MockHandler) as server:
        print(f"AI MOCK: http://127.0.0.1:{args.port}")
        print("Только локальная техническая проверка; медицинский анализ отключён.")
        try:
            server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
