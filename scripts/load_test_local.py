"""Локальный измеритель нагрузки AIDoctor/AI MOCK; без записи клинических данных.

Python 3.12, только стандартная библиотека.
Пример: python -m scripts.load_test_local --mode app --levels 2,5,10 --duration 10
"""

import argparse
import getpass
import json
import math
import os
import platform
import random
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

MAX_LEVEL = 100
MAX_RESPONSE_BYTES = 1_048_576
DEFAULT_TIMEOUT = 6
MAX_LEVELS = 12


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Перенаправления запрещены")


def parse_levels(raw: str) -> list[int]:
    try:
        values = [int(part.strip()) for part in raw.split(",")]
    except ValueError as exc:
        raise ValueError("Уровни должны быть целыми числами через запятую") from exc
    if not values or len(values) > MAX_LEVELS or any(not 1 <= x <= MAX_LEVEL for x in values):
        raise ValueError(f"Допустимо 1–{MAX_LEVEL} потоков, максимум {MAX_LEVELS} уровней")
    if values != sorted(set(values)):
        raise ValueError("Уровни должны возрастать без повторений")
    return values


def percentile(samples: list[float], fraction: float) -> float | None:
    if not samples:
        return None
    sorted_values = sorted(samples)
    index = max(0, math.ceil(len(sorted_values) * fraction) - 1)
    return round(sorted_values[index], 2)


def build_url(port: int) -> str:
    if not 1024 <= port <= 65535:
        raise ValueError("Локальный порт должен быть от 1024 до 65535")
    return f"http://127.0.0.1:{port}"


class LocalHttp:
    def __init__(self, base: str):
        if not base.startswith("http://127.0.0.1:"):
            raise ValueError("Нагрузочный тест доступен только по 127.0.0.1")
        self.base = base
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def get(self, path: str, token: str | None = None) -> dict | list:
        return self.request(path, token=token)

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        token: str | None = None,
        payload: dict | None = None,
    ) -> dict | list:
        if not path.startswith("/") or path.startswith("//") or "://" in path:
            raise ValueError("Некорректный путь API")
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
        req = Request(self.base + path, method=method, data=data, headers=headers)
        with self.opener.open(req, timeout=DEFAULT_TIMEOUT) as res:
            if res.status != 200 and not (method == "POST" and res.status == 201):
                raise RuntimeError(f"HTTP {res.status}")
            raw = res.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RuntimeError("Ответ превышает 1 МиБ")
        return json.loads(raw)


def authenticate(client: LocalHttp, username: str) -> str:
    password = getpass.getpass(f"Пароль {username}: ")
    try:
        result = client.request(
            "/api/v1/auth/login",
            method="POST",
            payload={"username": username, "password": password},
        )
    finally:
        password = None
    token = result.get("access_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("Нет токена авторизации")
    return token


def preflight_app(client: LocalHttp, doctor: str, patient: str) -> dict:
    health = client.get("/api/v1/health")
    if health.get("status") != "ok" or health.get("environment") not in ("local", "test"):
        raise RuntimeError("Нагрузка разрешена только при APP_ENV=local/test")
    doctor_token = authenticate(client, doctor)
    patient_token = authenticate(client, patient)
    me_doctor = client.get("/api/v1/auth/me", doctor_token)
    me_patient = client.get("/api/v1/auth/me", patient_token)
    if me_doctor.get("role") != "doctor" or me_patient.get("role") != "patient":
        raise RuntimeError("Указанные учётные записи должны быть врачом и пациентом")
    visible = client.get("/api/v1/patients", doctor_token)
    synthetic_ids = {
        item.get("id")
        for item in visible.get("items", [])
        if isinstance(item, dict)
        and isinstance(item.get("demographics"), dict)
        and item["demographics"].get("synthetic") is True
    }
    portal = client.get("/api/v1/patients/me/portal", patient_token)
    patient_id = portal.get("patient_id")
    if not patient_id or patient_id not in synthetic_ids:
        raise RuntimeError("Пациент не подтверждён как синтетический и доступный врачу")
    paths = {
        "doctor": [
            "/api/v1/patients",
            f"/api/v1/patients/{patient_id}/clinical-orders",
            f"/api/v1/patients/{patient_id}/ai-requests",
        ],
        "patient": [
            "/api/v1/patients/me/portal",
            "/api/v1/patients/me/clinical-orders",
            "/api/v1/patients/me/questionnaire-assignments",
            "/api/v1/patients/me/clinical-publications",
        ],
    }
    # Каждый маршрут обязан быть доступен до начала нагрузки.
    for role, role_paths in paths.items():
        token = doctor_token if role == "doctor" else patient_token
        for path in role_paths:
            client.get(path, token)
    return {"paths": paths, "tokens": {"doctor": doctor_token, "patient": patient_token}}


def mock_payload() -> dict:
    return {
        "schema_version": "aidoctor.mock_connection.v1",
        "request_id": str(uuid4()),
        "context_sha256": "f" * 64,
        "context_schema": "ai_agent_context.v1",
        "synthetic_confirmed": True,
        "approved_count": 0,
        "draft_count": 0,
    }


def preflight_mock(client: LocalHttp) -> None:
    try:
        health = client.get("/health")
    except (HTTPError, URLError) as exc:
        raise RuntimeError("На порту обнаружен не локальный AI MOCK") from exc
    if health.get("service") != "local_ai_mock" or health.get("llm_connected") is not False:
        raise RuntimeError("На порту обнаружен не локальный AI MOCK")
    response = client.request("/v1/simulate", method="POST", payload=mock_payload())
    if (
        response.get("analysis_performed") is not False
        or response.get("delivery_confirmed") is not True
    ):
        raise RuntimeError("Некорректный ответ имитатора")


@dataclass
class Observation:
    role: str
    elapsed_ms: float
    ok: bool
    error: str | None = None


def summarize(samples: list[Observation], duration_s: float, users: int) -> dict:
    good = [s.elapsed_ms for s in samples if s.ok]
    statuses = Counter(s.error for s in samples if not s.ok)
    n = len(samples)
    by_role = {}
    for role in ("doctor", "patient", "mock"):
        role_samples = [s for s in samples if s.role == role]
        if role_samples:
            lat = [s.elapsed_ms for s in role_samples if s.ok]
            by_role[role] = {
                "requests": len(role_samples),
                "errors": sum(not s.ok for s in role_samples),
                "p95_ms": percentile(lat, 0.95),
            }
    return {
        "virtual_clients": users,
        "duration_s": round(duration_s, 2),
        "requests": n,
        "ok": len(good),
        "errors": n - len(good),
        "error_rate_pct": round(100 * (n - len(good)) / n, 2) if n else 100.0,
        "rps": round(n / duration_s, 2) if duration_s > 0 else 0,
        "p50_ms": percentile(good, 0.50),
        "p95_ms": percentile(good, 0.95),
        "p99_ms": percentile(good, 0.99),
        "max_ms": round(max(good), 2) if good else None,
        "by_role": by_role,
        "errors_by_kind": dict(statuses),
    }


def stage(
    client: LocalHttp,
    *,
    users: int,
    duration: float,
    doctor_share: float,
    think_ms: int,
    mode: str,
    plan: dict | None,
) -> dict:
    finished = threading.Event()
    collected: list[Observation] = []
    lock = threading.Lock()
    if mode == "app":
        n_doctors = round(users * doctor_share)
        if users >= 2 and 0 < doctor_share < 1:
            n_doctors = max(1, min(users - 1, n_doctors))
        elif users == 1:
            n_doctors = 1 if doctor_share >= 0.5 else 0
    else:
        n_doctors = 0

    def worker(index: int) -> None:
        role = "mock" if mode == "mock" else ("doctor" if index < n_doctors else "patient")
        local = LocalHttp(client.base)
        rng = random.Random(index + 9184)
        local_samples: list[Observation] = []
        while not finished.is_set():
            before = time.perf_counter()
            error = None
            try:
                if role == "mock":
                    payload = local.request("/v1/simulate", method="POST", payload=mock_payload())
                    if payload.get("delivery_confirmed") is not True:
                        raise RuntimeError("mock_unconfirmed")
                else:
                    path = rng.choice(plan["paths"][role])
                    local.get(path, plan["tokens"][role])
            except HTTPError as exc:
                error = f"http_{exc.code}"
            except (URLError, TimeoutError, OSError):
                error = "connection_or_timeout"
            except (RuntimeError, ValueError, TypeError, json.JSONDecodeError):
                error = "bad_response"
            elapsed_ms = (time.perf_counter() - before) * 1000
            local_samples.append(Observation(role, round(elapsed_ms, 2), error is None, error))
            if think_ms:
                finished.wait(think_ms / 1000 * rng.uniform(0.8, 1.2))
        with lock:
            collected.extend(local_samples)

    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=users) as executor:
        futures = [executor.submit(worker, i) for i in range(users)]
        time.sleep(duration)
        finished.set()
        for future in futures:
            future.result()
    elapsed = time.perf_counter() - start
    return summarize(collected, elapsed, users)


def main() -> None:
    parser = argparse.ArgumentParser(description="Локальный синтетический нагрузочный тест")
    parser.add_argument("--mode", choices=("app", "mock"), default="app")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--doctor", default="doctor_ui1")
    parser.add_argument("--patient", default="patient_ui1")
    parser.add_argument("--levels", default="2,5,10,20")
    parser.add_argument("--duration", type=int, default=10, help="Секунд на уровень")
    parser.add_argument("--think-ms", type=int, default=400, help="Пауза между действиями")
    parser.add_argument("--doctor-share", type=float, default=0.3, help="Доля врачебных потоков")
    parser.add_argument("--p95-limit", type=int, default=800, help="Целевой p95, мс")
    parser.add_argument("--error-limit", type=float, default=1.0, help="Целевой предел ошибок, %%")
    parser.add_argument("--profile", default="локальная машина", help="Название профиля железа")
    parser.add_argument("--output", help="Путь к JSON-отчёту без персональных данных")
    args = parser.parse_args()
    try:
        levels = parse_levels(args.levels)
        if not 5 <= args.duration <= 180:
            raise ValueError("Длительность этапа должна быть 5–180 секунд")
        if not 0 <= args.think_ms <= 10_000:
            raise ValueError("Пауза должна быть от 0 до 10000 мс")
        if not 0 <= args.doctor_share <= 1 or not math.isfinite(args.doctor_share):
            raise ValueError("Доля врачей должна быть от 0 до 1")
        if args.p95_limit < 1 or not 0 <= args.error_limit <= 100:
            raise ValueError("Неверные критерии качества")
        if len(args.profile) > 120:
            raise ValueError("Название профиля слишком длинное")
        port = args.port if args.port is not None else (8000 if args.mode == "app" else 8765)
        client = LocalHttp(build_url(port))
        plan = preflight_app(client, args.doctor, args.patient) if args.mode == "app" else None
        if args.mode == "mock":
            preflight_mock(client)
        print("Начало локального теста: только чтение данных AIDoctor; ни одной записи назначения.")
        results = []
        for level in levels:
            item = stage(
                client,
                users=level,
                duration=args.duration,
                doctor_share=args.doctor_share,
                think_ms=args.think_ms,
                mode=args.mode,
                plan=plan,
            )
            item["within_latency_target"] = (
                item["p95_ms"] is not None and item["p95_ms"] <= args.p95_limit
            )
            item["within_error_target"] = (
                bool(item["requests"]) and item["error_rate_pct"] <= args.error_limit
            )
            item["passed"] = item["within_latency_target"] and item["within_error_target"]
            results.append(item)
            status = "OK" if item["passed"] else "ПОРОГ ПРЕВЫШЕН"
            print(
                f"{level:>3} потоков | {item['rps']:>7} запрос/с | "
                f"p95={item['p95_ms']} мс | p99={item['p99_ms']} мс | "
                f"ошибки={item['error_rate_pct']}% | {status}"
            )
        report = {
            "schema_version": "aidoctor.load_report.v1",
            "measured_at_utc": datetime.now(UTC).isoformat(),
            "mode": args.mode,
            "hardware_profile": args.profile,
            "client_host": platform.platform(),
            "client_logical_cpus": os.cpu_count(),
            "role_mix": {"doctor_share": args.doctor_share, "patient_share": 1 - args.doctor_share}
            if args.mode == "app"
            else None,
            "test_parameters": {
                "duration_per_level_s": args.duration,
                "think_ms": args.think_ms,
                "p95_limit_ms": args.p95_limit,
                "error_limit_pct": args.error_limit,
                "distinct_user_accounts": 2 if args.mode == "app" else 0,
            },
            "results": results,
            "limitations": [
                "Виртуальные потоки не равны количеству независимых пользователей.",
                "Использованы только две учётные записи, а не отдельная учётная запись на поток.",
                "Измерен локальный HTTP/БД без браузерной отрисовки и без настоящей LLM.",
                "Нужен отдельный мониторинг CPU/RAM/соединений БД для решения о ёмкости.",
            ],
        }
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Отчёт: {path}")
        stable = [x["virtual_clients"] for x in results if x["passed"]]
        highest = max(stable) if stable else "нет"
        print(f"Максимальный пройденный УРОВЕНЬ данного прогона: {highest}")
        print("Это не подтверждённая ёмкость production и не количество уникальных пользователей.")
    except (ValueError, RuntimeError, HTTPError, URLError, OSError, KeyError, TypeError) as exc:
        # Не включаем HTTP-тела или токены в сообщение об ошибке.
        print(f"ТЕСТ ОСТАНОВЛЕН: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
