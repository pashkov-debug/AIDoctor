"""Неразрушающая проверка HTTPS и доступности приложения AIDoctor.

Использование: python3 deploy/smoke_deploy.py https://ваш-домен
Для локальной стадии с сертификатом Caddy: --local-ca (только localhost).
"""

import argparse
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def verify(base_url: str, local_ca: bool = False) -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Требуется URL https://... без логина и пароля")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Укажите только адрес сервера без пути, параметров и фрагмента")
    if local_ca and parsed.hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("--local-ca разрешён только для localhost/127.0.0.1")
    context = ssl._create_unverified_context() if local_ca else ssl.create_default_context()
    base = base_url.rstrip("/")
    for path, marker in (("/api/v1/health", "json"), ("/app", "html")):
        req = Request(base + path, headers={"Accept": "application/json, text/html"})
        with urlopen(req, timeout=8, context=context) as response:
            if response.status != 200:
                raise RuntimeError(f"{path}: HTTP {response.status}")
            raw = response.read(128 * 1024)
            if marker == "json":
                data = json.loads(raw.decode("utf-8"))
                if data.get("status") != "ok" or data.get("environment") != "production":
                    raise RuntimeError("Неверный статус /health или APP_ENV")
            elif "<html" not in raw.decode("utf-8").lower():
                raise RuntimeError("Нет HTML-страницы AIDoctor")
        print(f"OK {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test серверного AIDoctor")
    parser.add_argument("base_url")
    parser.add_argument("--local-ca", action="store_true")
    args = parser.parse_args()
    try:
        verify(args.base_url, args.local_ca)
    except (
        ValueError,
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        RuntimeError,
        json.JSONDecodeError,
    ) as exc:
        print(f"Ошибка smoke-test: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
