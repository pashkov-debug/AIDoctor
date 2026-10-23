"""Сквозная проверка FastAPI -> локальный AI MOCK, только для синтетического пациента.

Запуск: python -m scripts.smoke_ai_connection
Пароль запрашивается интерактивно, контекст в MOCK НЕ передаётся.
"""

import argparse
import getpass
import hashlib
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler,
    ProxyHandler,
    Request,
    build_opener,
)
from uuid import uuid4

from scripts.mock_ai_server import REQUEST_SCHEMA, RESPONSE_SCHEMA

TIMEOUT_SECONDS = 8


class ForbidRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Неожиданное перенаправление HTTP — соединение остановлено")


OPENER = build_opener(ProxyHandler({}), ForbidRedirect())


def canonical_sha256(value: dict) -> str:
    data = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def http_json(
    base: str,
    path: str,
    *,
    method: str = "GET",
    token: str | None = None,
    payload: dict | None = None,
) -> dict | list:
    data = (
        json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if payload is not None
        else None
    )
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(base + path, data=data, headers=headers, method=method)
    try:
        with OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status not in (200, 201):
                raise RuntimeError(f"Неожиданный HTTP {response.status}")
            return json.loads(response.read(512 * 1024).decode("utf-8"))
    except HTTPError as exc:
        # Тело может содержать медицинскую информацию, поэтому не печатаем его.
        raise RuntimeError(f"{method} {path}: HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {path}: соединение недоступно") from exc


def choose_patient(items: list, patient_id: str | None = None) -> dict:
    candidates = [
        item
        for item in items
        if isinstance(item, dict)
        and isinstance(item.get("demographics"), dict)
        and item["demographics"].get("synthetic") is True
    ]
    if patient_id:
        candidates = [p for p in candidates if p.get("id") == patient_id]
    if not candidates:
        raise ValueError("Нет доступного синтетического пациента")
    return sorted(candidates, key=lambda item: (item.get("alias", ""), item["id"]))[0]


def run(doctor: str, patient_id: str | None, app_port: int, mock_port: int, fresh: bool) -> None:
    app = f"http://127.0.0.1:{app_port}"
    mock = f"http://127.0.0.1:{mock_port}"
    health = http_json(mock, "/health")
    if health.get("service") != "local_ai_mock" or health.get("llm_connected") is not False:
        raise RuntimeError("На порту симулятора находится неизвестный сервис")
    print("[1/5] Локальный имитатор отвечает")
    password = getpass.getpass(f"Пароль врача {doctor}: ")
    if not password:
        raise ValueError("Пароль пуст")
    login = http_json(
        app,
        "/api/v1/auth/login",
        method="POST",
        payload={"username": doctor, "password": password},
    )
    password = ""
    token = login["access_token"]
    me = http_json(app, "/api/v1/auth/me", token=token)
    if me.get("role") != "doctor":
        raise RuntimeError("Только роль doctor может запускать этот сценарий")
    patients = http_json(app, "/api/v1/patients", token=token)
    patient = choose_patient(patients["items"], patient_id)
    pid = patient["id"]
    print(f"[2/5] Врач авторизован; выбран синтетический пациент: {patient['alias']}")
    base = f"/api/v1/patients/{pid}/ai-requests"
    requests = http_json(app, base, token=token)
    eligible = [r for r in requests if r.get("orders_review_available") is True]
    if eligible and not fresh:
        request_id = eligible[0]["id"]
        print("[3/5] Повторно использован подготовленный AI-запрос")
    else:
        created = http_json(
            app,
            base,
            token=token,
            method="POST",
            payload={
                "request_key": str(uuid4()),
                "question": "Проверка маршрута связи с AI без клинического анализа.",
                "attachment_ids": [],
            },
        )
        request_id = created["id"]
        print("[3/5] Создан технический AI-запрос в AIDoctor")
    context = http_json(app, f"{base}/{request_id}/agent-context", token=token)
    if (
        context.get("schema_version") != "ai_agent_context.v1"
        or context.get("request_id") != request_id
        or context.get("patient_id") != pid
        or context.get("doctor_id") != me["id"]
        or context.get("llm_dispatch_enabled") is not False
    ):
        raise RuntimeError("Ответ AIDoctor не соответствует контракту контекста")
    orders = context.get("orders_review", {})
    if orders.get("schema_version") != "orders_for_ai_review.v1":
        raise RuntimeError("Отсутствует контракт проектов назначений")
    approved = orders.get("approved_orders")
    drafts = orders.get("proposed_orders_for_review")
    if not isinstance(approved, list) or not isinstance(drafts, list):
        raise RuntimeError("Некорректные списки назначений")
    digest = canonical_sha256(context)
    print("[4/5] Защищённый снимок контекста получен от AIDoctor")
    # В MOCK передаём ТОЛЬКО технические числа и checksum, без клинической информации.
    envelope = {
        "schema_version": REQUEST_SCHEMA,
        "request_id": request_id,
        "context_sha256": digest,
        "context_schema": context["schema_version"],
        "synthetic_confirmed": True,
        "approved_count": len(approved),
        "draft_count": len(drafts),
    }
    receipt = http_json(mock, "/v1/simulate", method="POST", payload=envelope)
    if (
        receipt.get("schema_version") != RESPONSE_SCHEMA
        or receipt.get("service") != "local_ai_mock"
        or receipt.get("origin") != "synthetic_connection_test"
        or receipt.get("delivery_confirmed") is not True
        or receipt.get("llm_connected") is not False
        or receipt.get("analysis_performed") is not False
        or receipt.get("recommendations") != []
        or receipt.get("request_id") != request_id
        or receipt.get("received_context_sha256") != digest
        or receipt.get("approved_count") != len(approved)
        or receipt.get("draft_count") != len(drafts)
    ):
        raise RuntimeError("Подтверждение имитатора не совпадает с запросом")
    print("[5/5] Локальное соединение подтверждено")
    print(f"Запрос: {request_id}")
    print(f"Назначения: утверждённые={len(approved)}, черновики={len(drafts)}")
    print("ГОТОВО: транспорт работает. LLM НЕ вызывалась, анализ и назначения НЕ создавались.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка связи AIDoctor и AI MOCK")
    parser.add_argument("--doctor", default="doctor_ui1")
    parser.add_argument("--patient-id", help="ID доступного синтетического пациента")
    parser.add_argument("--app-port", type=int, default=8000)
    parser.add_argument("--mock-port", type=int, default=8765)
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Создать новый снимок AI-запроса вместо повторного использования",
    )
    args = parser.parse_args()
    if not all(1024 <= p <= 65535 for p in (args.app_port, args.mock_port)):
        parser.error("Порт должен быть от 1024 до 65535")
    if args.app_port == args.mock_port:
        parser.error("У AIDoctor и имитатора должны быть разные порты")
    try:
        run(args.doctor, args.patient_id, args.app_port, args.mock_port, args.fresh)
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
