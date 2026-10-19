"""Публичный read-only HTTP Bridge: только отдельно посеянная демонстрационная БД."""

from collections.abc import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from demo_bridge.config import demo_url_from_env
from demo_bridge.contract import (
    DemoContextEnvelope,
    DemoDataError,
    DemoEnvelope,
    context_response,
    patient_response,
    read_verified_case,
)

SessionFactory = Callable[[], Session]


def create_app(*, session_factory: SessionFactory | None = None) -> FastAPI:
    if session_factory is None:
        engine = create_engine(demo_url_from_env(), pool_pre_ping=True)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    application = FastAPI(
        title="AIDoctor Demo Bridge (synthetic only)",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    @application.middleware("http")
    async def safe_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def _read(kind: str) -> dict:
        try:
            with session_factory() as session:
                if kind == "patient":
                    return patient_response(session)
                if kind == "context":
                    return context_response(session)
                read_verified_case(session)
                return {"status": "ok", "synthetic": True, "read_only": True}
        except Exception as exc:
            # Не включать SQL, секреты и содержимое данных в публичные ответы.
            if isinstance(exc, DemoDataError):
                detail = "Демонстрационные данные не прошли проверку"
            else:
                detail = "Демонстрационный источник недоступен"
            raise HTTPException(status_code=503, detail=detail) from None

    @application.get("/health")
    def health() -> dict:
        return _read("health")

    @application.get("/demo/v1/patient", response_model=DemoEnvelope)
    def get_demo_patient() -> dict:
        return _read("patient")

    @application.get("/demo/v1/context", response_model=DemoContextEnvelope)
    def get_demo_context() -> dict:
        return _read("context")

    @application.exception_handler(405)
    async def method_denied(_request: Request, _exc):
        return JSONResponse(status_code=405, content={"detail": "Read-only"})

    return application


# Не создаём engine при импорте: uvicorn --factory вызывает create_app после установки env.
