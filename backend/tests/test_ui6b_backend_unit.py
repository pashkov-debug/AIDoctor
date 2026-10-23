"""Тренировочный AI-режим нельзя включить в production."""

from app.services import ai_review


def test_training_mode_disabled_in_production(monkeypatch):
    monkeypatch.setenv("AIDOCTOR_ALLOW_SYNTHETIC_AI_DRAFTS", "1")
    monkeypatch.setattr(ai_review.settings, "app_env", "production")
    assert ai_review._enabled() is False


def test_training_mode_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(ai_review.settings, "app_env", "local")
    monkeypatch.delenv("AIDOCTOR_ALLOW_SYNTHETIC_AI_DRAFTS", raising=False)
    assert ai_review._enabled() is False
