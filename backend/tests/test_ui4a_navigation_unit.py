"""UI-4A/NAV: структура бокового меню без запуска PostgreSQL.

Динамические переходы дополнительно проверяются браузерным smoke-тестом.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "app" / "web"
HTML = WEB / "index.html"
JS = WEB / "assets" / "app.js"


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []

    def handle_starttag(self, tag, attrs):
        self.items.append((tag, dict(attrs)))


def elements():
    parser = Elements()
    parser.feed(HTML.read_text(encoding="utf-8"))
    return parser.items


def test_navigation_has_all_roles_and_ai_route():
    items = elements()
    buttons = [attrs for tag, attrs in items if tag == "button"]
    roles = {"doctor": 9, "patient": 4, "admin": 5}
    for role, count in roles.items():
        assert (
            len(
                [
                    item
                    for item in buttons
                    if item.get("data-view") and item.get("data-role") == role
                ]
            )
            == count
        )
    ai = [item for item in buttons if item.get("id") == "ai-nav"]
    assert len(ai) == 1
    assert ai[0]["data-view"] == "ai"
    assert ai[0]["data-role"] == "doctor"
    assert any(attrs.get("id") == "ai-view" for _, attrs in items)


def test_navigation_and_clinical_sections_match():
    items = elements()
    buttons = [attrs for tag, attrs in items if tag == "button"]
    for view in ("clinical", "patient", "admin"):
        links = {
            attrs["data-panel"]
            for attrs in buttons
            if attrs.get("data-view") == view and "data-panel" in attrs
        }
        panels = {
            attrs["data-panel"] for _, attrs in items if attrs.get("data-panel-group") == view
        }
        assert links == panels
    ids = [attrs["id"] for _, attrs in items if "id" in attrs]
    assert len(ids) == len(set(ids))


def test_cache_buster_and_role_guard_remain():
    html = HTML.read_text(encoding="utf-8")
    js = JS.read_text(encoding="utf-8")
    assert "app.js?v=ui4a-nav-1" in html
    assert "style.css?v=ui4a-nav-1" in html
    assert "node.dataset.role !== user.role" in js
    assert 'name === "ai"' in js
    assert "renderActivePanels(name)" in js
    assert "state.clinicalPatient" in js
    assert not re.search(r"<script[^>]+https?://", html)
