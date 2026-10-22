"""UI-2B: неизменность источников и ограничений сценариев."""

from pathlib import Path

from backend.scripts.seed_ui2b_synthetic import (
    FIRST_EVENTS,
    FIRST_OBSERVATIONS,
    FIRST_VISITS,
    SECOND_EVENTS,
    SECOND_OBSERVATIONS,
    SECOND_VISITS,
    SEED_VERSION,
)


def test_two_distinct_rich_synthetic_scenarios() -> None:
    assert SEED_VERSION.startswith("synthetic:")
    assert len(FIRST_VISITS) >= 5
    assert len(SECOND_VISITS) >= 7
    assert len(FIRST_EVENTS) >= 10
    assert len(SECOND_EVENTS) >= 12
    assert len(FIRST_OBSERVATIONS) >= 7
    assert len(SECOND_OBSERVATIONS) >= 9
    for offsets in (
        FIRST_VISITS,
        SECOND_VISITS,
        FIRST_EVENTS,
        SECOND_EVENTS,
        FIRST_OBSERVATIONS,
        SECOND_OBSERVATIONS,
    ):
        assert max(row[0] for row in offsets) < 0
        assert min(row[0] for row in offsets) <= -30


def test_browser_has_explicit_visit_navigation_and_visibility_explanation() -> None:
    root = Path(__file__).resolve().parents[1] / "app" / "web"
    html = (root / "index.html").read_text(encoding="utf-8")
    js = (root / "assets" / "app.js").read_text(encoding="utf-8")
    assert 'id="clinical-visits-section"' in html
    assert 'id="clinical-observations"' in html
    assert 'data-clinical-target="clinical-visits-section"' in html
    assert "Визиты и история →" in js
    assert "renderClinicalObservations(context)" in js
    assert "Ещё не опубликовано" in html
