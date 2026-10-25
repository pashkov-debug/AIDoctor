"""Review определяется правами врача и состоянием пациента, а не окружением."""

from datetime import UTC, datetime
from types import SimpleNamespace

from app.services import ai_review


def test_review_does_not_depend_on_test_mode_or_synthetic_marker(monkeypatch):
    monkeypatch.setenv("AIDOCTOR_ALLOW_SYNTHETIC_AI_DRAFTS", "0")
    monkeypatch.setenv("APP_ENV", "production")
    row = SimpleNamespace(deleted_at=None, demographics_json={})
    db = SimpleNamespace(get=lambda *_: row)
    assert ai_review.enabled_for_patient(db, "patient") is True
    row.demographics_json = {"synthetic": True}
    assert ai_review.enabled_for_patient(db, "patient") is True
    row.deleted_at = datetime.now(UTC)
    assert ai_review.enabled_for_patient(db, "patient") is False
