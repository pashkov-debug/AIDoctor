from fastapi import FastAPI

from app.api.routes.encounters import (
    router as encounters_router,
)
from app.api.routes.health import (
    router as health_router,
)
from app.api.routes.history_events import (
    router as history_events_router,
)
from app.api.routes.patients import (
    router as patients_router,
)
from app.api.routes.questionnaires import (
    router as questionnaires_router,
)
from app.core.config import settings


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version="0.4.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    routers = (
        health_router,
        patients_router,
        encounters_router,
        questionnaires_router,
        history_events_router,
    )

    for router in routers:
        application.include_router(
            router,
            prefix=settings.api_v1_prefix,
        )

    return application


app = create_app()
