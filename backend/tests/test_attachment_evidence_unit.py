"""Unit: нормализация, хэширование, отказ от молчаливой интерпретации."""

import hashlib

import pytest
from app.schemas.attachment_evidence_draft import EvidenceDraftCreate
from app.services.attachment_evidence import InvalidEvidenceDraft, normalize_evidence
from pydantic import ValidationError


def test_unicode_normalization_is_deterministic():
    locator, text, digest = normalize_evidence("  стр. 1  ", "  cafe\u0301 \n ")
    assert locator == "стр. 1"
    assert text == "café"
    assert digest == hashlib.sha256("café".encode()).hexdigest()


@pytest.mark.parametrize(
    ("locator", "excerpt"),
    [
        (" ", "Текст"),
        ("\n", "Текст"),
        ("страница\x00", "Текст"),
        ("стр. 1", "  "),
        ("стр. 1", "\x00"),
        ("стр. 1", "синтетический\x01фрагмент"),
        ("x" * 121, "Текст"),
        ("стр. 1", "x" * 2001),
    ],
)
def test_invalid_manual_draft_rejected(locator, excerpt):
    with pytest.raises(InvalidEvidenceDraft):
        normalize_evidence(locator, excerpt)


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        EvidenceDraftCreate(
            source_locator="стр. 1",
            excerpt="Только тест",
            verification_status="verified",
        )


def test_normalization_does_not_transform_semantics():
    _, text, digest = normalize_evidence("Абзац 1", "  ЧСС:  60\nАД:  120/80 ")
    assert text == "ЧСС:  60\nАД:  120/80"
    assert digest == hashlib.sha256(text.encode()).hexdigest()
