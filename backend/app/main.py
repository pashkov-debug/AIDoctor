from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.core.config import settings


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    application.include_router(
        health_router,
        prefix=settings.api_v1_prefix,
    )

    return application


app = create_app()
