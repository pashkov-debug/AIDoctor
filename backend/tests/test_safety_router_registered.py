"""Проверки регистрации маршрутов для FastAPI с вложенными роутерами."""

from app.api.routes.safety_alerts import router as safety_router
from app.main import create_app
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient


def _operations(application) -> set[tuple[str, str]]:
    """OpenAPI — публичное представление путей, включая вложенные APIRouter."""
    schema = application.openapi()
    methods = {"get", "post", "put", "patch", "delete"}
    return {
        (method.upper(), path)
        for path, description in schema["paths"].items()
        for method in description
        if method in methods
    }


def test_safety_routes_are_registered_exactly_once():
    application = create_app()
    expected = {
        ("POST", "/api/v1/patients/{patient_id}/safety-alerts"),
        ("GET", "/api/v1/patients/{patient_id}/safety-alerts"),
        ("POST", "/api/v1/patients/{patient_id}/safety-alerts/{alert_id}/ack"),
    }

    published = _operations(application)
    assert expected <= published, f"Safety API не зарегистрирован: {expected - published}"

    # FastAPI >= 0.137 хранит вложенные маршрутизаторы как _IncludedRouter.
    included = [
        route
        for route in application.routes
        if getattr(route, "original_router", None) is safety_router
    ]
    if included:
        assert len(included) == 1, "Safety Router подключён несколько раз"
    else:
        # Старые версии FastAPI копируют APIRoute в корневой список.
        registered = [
            (method, route.path)
            for route in application.routes
            if isinstance(route, APIRoute)
            for method in (route.methods or ())
            if (method, route.path) in expected
        ]
        assert len(registered) == len(expected)
        assert set(registered) == expected


def test_context_and_attachments_routes_are_preserved():
    published = _operations(create_app())
    expected = {
        ("GET", "/api/v1/patients/{patient_id}/context"),
        ("GET", "/api/v1/patients/{patient_id}/context/digest"),
        ("POST", "/api/v1/patients/{patient_id}/context/delta"),
        ("POST", "/api/v1/patients/{patient_id}/attachments"),
    }
    assert expected <= published, f"Отсутствуют маршруты: {expected - published}"


def test_safety_routes_require_authentication():
    application = create_app()
    base = "/api/v1/patients/unknown-patient/safety-alerts"
    with TestClient(application) as client:
        responses = [
            client.get(base),
            client.post(
                base,
                json={"reason_code": "clinician_review", "priority": "standard"},
            ),
            client.post(f"{base}/unknown-alert/ack"),
        ]
    assert [item.status_code for item in responses] == [401, 401, 401], [
        (item.status_code, item.text) for item in responses
    ]
