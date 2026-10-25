"""UI-4B: интерфейс врача не показывает внутреннее представление БД."""

from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "app" / "web"


class _ButtonParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.buttons = {}
        self.ids = []

    def handle_starttag(self, tag, attrs):
        options = dict(attrs)
        if "id" in options:
            self.ids.append(options["id"])
        if tag == "button" and "id" in options:
            self.buttons[options["id"]] = ""

    def handle_data(self, data):
        # Текущие кнопки не содержат вложенных элементов с текстом.
        if self.lasttag == "button":
            for key in reversed(self.buttons):
                if not self.buttons[key]:
                    self.buttons[key] = data.strip()
                    break


def test_clinical_confirmation_labels_and_unique_ids():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    parser = _ButtonParser()
    parser.feed(html)
    assert len(parser.ids) == len(set(parser.ids))
    assert "Предпросмотр выбранных изменений" in html
    assert "Подтвердить и применить" in html
    assert "Опубликовать пациенту" in html
    assert "Просмотр изменений БД" not in html
    assert '<div id="order-approval-preview"' in html


def test_preview_is_clinical_and_backend_validation_unchanged():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    preview_start = js.index('$("ai-review-preview").addEventListener')
    approve_start = js.index('$("ai-review-approve").addEventListener', preview_start)
    clinical_preview = js[preview_start:approve_start]
    assert "renderClinicalPreviewFields(change.original)" in clinical_preview
    assert "renderClinicalPreviewFields(change.final, change.original)" in clinical_preview
    assert "Таблица ${change.table}" not in clinical_preview
    assert "Контрольная сумма предпросмотра" not in clinical_preview
    assert "JSON.stringify(change" not in clinical_preview
    assert "preview_sha256: reviewPreview.preview_sha256" in js[approve_start:]
    assert "confirm_patient_visibility:true" in js[approve_start:]
    assert "confirm_clinical_review:true" in js[approve_start:]
    assert "description.textContent = clinicalPreviewValue" in js
