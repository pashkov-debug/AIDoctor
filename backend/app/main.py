from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.access import router as access_router
from app.api.routes.admin import router as admin_router
from app.api.routes.ai_workspace import router as ai_workspace_router
from app.api.routes.attachment_evidence import router as attachment_evidence_router
from app.api.routes.attachment_security import router as attachment_security_router
from app.api.routes.attachments import router as attachments_router
from app.api.routes.auth import router as auth_router
from app.api.routes.clinical_orders import router as clinical_orders_router
from app.api.routes.clinical_publication import router as clinical_publication_router
from app.api.routes.context import router as context_router
from app.api.routes.doctor_settings import router as doctor_settings_router
from app.api.routes.encounters import router as encounters_router
from app.api.routes.health import router as health_router
from app.api.routes.history_events import router as history_events_router
from app.api.routes.patient_portal import router as patient_portal_router
from app.api.routes.patients import router as patients_router
from app.api.routes.questionnaire_assignments import router as questionnaire_assignments_router
from app.api.routes.questionnaires import router as questionnaires_router
from app.api.routes.safety_alerts import router as safety_router
from app.api.routes.safety_followups import router as safety_followups_router
from app.api.routes.safety_in_app_notifications import router as safety_inbox_router
from app.api.routes.safety_notification_routes import router as safety_routes_router
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
        auth_router,
        admin_router,
        doctor_settings_router,
        access_router,
        patient_portal_router,
        clinical_publication_router,
        clinical_orders_router,
        patients_router,
        encounters_router,
        questionnaires_router,
        questionnaire_assignments_router,
        history_events_router,
        context_router,
        ai_workspace_router,
        attachments_router,
        attachment_security_router,
        attachment_evidence_router,
        safety_router,
        safety_routes_router,
        safety_inbox_router,
        safety_followups_router,
    )
    for router in routers:
        application.include_router(router, prefix=settings.api_v1_prefix)
    web_dir = Path(__file__).resolve().parent / "web"
    application.mount("/app/assets", StaticFiles(directory=web_dir / "assets"), name="web-assets")

    @application.get("/", include_in_schema=False)
    def home_redirect() -> RedirectResponse:
        return RedirectResponse("/app", status_code=307)

    @application.get("/app", include_in_schema=False)
    @application.get("/app/", include_in_schema=False)
    def web_app() -> FileResponse:
        return FileResponse(
            web_dir / "index.html",
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'self'; style-src 'self'; "
                    "connect-src 'self'; img-src 'self'; base-uri 'none'; "
                    "form-action 'self'; frame-ancestors 'none'"
                ),
            },
        )

    return application


app = create_app()
