"""Проверяем пользовательские экраны и изоляцию тренировочного AI UI."""

from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "app" / "web"


class Inspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.entries: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag, attrs):
        self.entries.append((tag, dict(attrs)))


def test_clean_labels_and_existing_role_menus():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    parser = Inspector()
    parser.feed(html)
    ids = [attrs["id"] for _, attrs in parser.entries if "id" in attrs]
    assert len(ids) == len(set(ids))

    for role, count in (("doctor", 3), ("patient", 4), ("admin", 5)):
        buttons = [
            attrs
            for tag, attrs in parser.entries
            if tag == "button" and attrs.get("data-role") == role and attrs.get("data-view")
        ]
        assert len(buttons) == count

    for technical in (
        "ЛОКАЛЬНАЯ РАЗРАБОТКА",
        "Граница UI-",
        "Ограничения UI-",
        "UI-4B:",
        "Просмотр изменений БД",
        "PostgreSQL",
        "FastAPI",
        "Контрольная сумма",
        "AIDOCTOR_ALLOW_SYNTHETIC_AI_DRAFTS",
    ):
        assert technical not in html

    review = [attrs for _, attrs in parser.entries if attrs.get("id") == "ai-review-workspace"]
    assert len(review) == 1 and "hidden" in review[0]
    assert "Предпросмотр выбранных изменений" in html
    assert "Подтвердить и применить" in html
    assert "Российские клинические рекомендации" in html


def test_client_uses_server_flag_and_excludes_internal_ai_data():
    js = (WEB / "assets" / "app.js").read_text(encoding="utf-8")
    assert "info.synthetic_review_enabled === true" in js
    assert '$("ai-review-workspace").hidden = !syntheticReviewEnabled' in js
    assert "if (syntheticReviewEnabled) {" in js
    assert "Контекст: ${item.context_sha256" not in js
    assert "JSON.stringify(item.fact" not in js
    assert "renderClinicalFact(item.fact)" in js
    assert "node.dataset.role !== user.role" in js
    assert "preview_sha256: reviewPreview.preview_sha256" in js
    assert "confirm_clinical_review:true" in js


def test_adaptive_layout_and_cache_updates():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "assets" / "style.css").read_text(encoding="utf-8")
    assert "app.js?v=workspace-s5-1" in html
    assert "style.css?v=workspace-s5-1" in html
    assert "ai-three-panels > .panel:last-child" in css
    assert ".visually-hidden" in css
    assert "prefers-reduced-motion" in css
