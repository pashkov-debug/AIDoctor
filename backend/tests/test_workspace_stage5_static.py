"""Этап 5: целостность общего пациента и устойчивость UI к частичным ошибкам API."""

from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "app" / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
CSS = (WEB / "assets" / "style.css").read_text(encoding="utf-8")


class _Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_patient_selector_in_ai_is_readonly_and_associated_with_card():
    parsed = _Elements()
    parsed.feed(HTML)
    matches = [
        attrs
        for tag, attrs in parsed.elements
        if tag == "select" and attrs.get("id") == "ai-patient-select"
    ]
    assert len(matches) == 1
    assert "disabled" in matches[0]
    assert "state.clinicalPatient?.id" in JS
    assert "patients.find(item => item.id === patientId)" in JS
    assert "select.append(option);" in JS
    assert '$("ai-patient-select").addEventListener("change"' not in JS
    assert "#ai-patient-select:disabled" in CSS


def test_clinical_loading_is_independent_and_discards_old_requests():
    block = JS.split("async function loadClinical()", 1)[1].split(
        'document.querySelectorAll("[data-clinical-target]")', 1
    )[0]
    assert "const epoch = ++clinicalLoadEpoch;" in block
    assert "Promise.allSettled(" in block
    assert 'failed(0, "Визиты")' in block
    assert 'failed(1, "История")' in block
    assert 'failed(3, "Сводка")' in block
    assert "state.clinicalPatient?.id !== patient.id" in block
    assert "epoch !== clinicalLoadEpoch" in block
    assert "loadClinicalOrders(patient.id, epoch)" in block
    assert "loadClinicalTests(patient.id, epoch)" in block


def test_stale_order_and_test_errors_cannot_override_new_patient():
    orders = JS.split("async function loadClinicalOrders(", 1)[1].split(
        '$("order-form").addEventListener', 1
    )[0]
    tests = JS.split("async function loadClinicalTests(", 1)[1].split(
        '$("clinical-test-form").addEventListener', 1
    )[0]
    for block in (orders, tests):
        assert "clinicalEpoch !== clinicalLoadEpoch" in block
        assert block.count("state.clinicalPatient?.id !== patientId") >= 2


def test_new_review_clears_previous_request_before_showing_another():
    block = JS.split("async function openAIReview(", 1)[1].split(
        '$("ai-demo-create").addEventListener', 1
    )[0]
    assert block.index("clearAIReview();") < block.index("reviewRequestId = requestId;")
    assert "epoch !== reviewEpoch" in block
    assert "renderReviewDraft()" in block


def test_reject_is_single_flight_and_patient_bound():
    block = JS.split('$("ai-review-reject").addEventListener', 1)[1]
    assert "button.disabled = true;" in block
    assert 'patientId !== $("ai-patient-select").value' in block
    assert "epoch !== reviewEpoch" in block
    assert 'button.disabled = reviewDraft?.status !== "open";' in block


def test_api_and_ai_provenance_are_not_faked():
    assert "info.synthetic_review_enabled === true" in JS
    assert "Сохранённый тестовый AI-анализ" in JS
    assert 'open.textContent = "Проверить предложения";' in JS
    assert "Не удалось получить AI-ответ" in JS
    assert "не является ответом AI" in JS
    assert 'id="ai-review-workspace"' in HTML
