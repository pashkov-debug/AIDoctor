"""Проверка контрактов единого рабочего места без запуска сервера."""

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "app" / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "assets" / "app.js").read_text(encoding="utf-8")


class _Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if props.get("id"):
            self.ids.append(props["id"])


def test_unique_element_ids():
    parser = _Ids()
    parser.feed(HTML)
    assert all(count == 1 for count in Counter(parser.ids).values())


def test_doctor_workspace_keeps_existing_modules_in_one_area():
    assert 'id="patient-workspace-grid"' in HTML
    assert 'id="doctor-ai-column"' in HTML
    assert 'id="clinical-timeline-items"' in HTML
    for element_id in (
        "clinical-visits-section",
        "clinical-history-section",
        "clinical-observations-section",
        "clinical-orders-section",
        "clinical-tests-section",
        "clinical-digest-section",
        "ai-view",
        "ai-request-form",
        "ai-requests",
        "ai-proposal-cards",
    ):
        assert f'id="{element_id}"' in HTML
    assert '$("doctor-ai-column").append($("ai-view"))' in JS


def test_patient_switch_and_manual_entries_are_connected():
    assert "clearAIWorkspace();" in JS
    assert "state.clinicalPatient?.id !== item.patient_id" in JS
    assert "state.clinicalPatient?.id !== patientId" in JS
    assert "/observations" in JS
    assert 'id="clinical-history-form"' in HTML
    assert 'id="clinical-observation-form"' in HTML
    assert "/history-events" in JS
