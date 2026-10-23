"""Учебный каталог, strict-int и детерминированное правило риска."""

import pytest
from app.clinical.demo_test_catalog import CATALOG, definition, score
from app.schemas.questionnaire_assignment import AssignDemoTest, SubmitDemoTest
from pydantic import ValidationError


def test_catalog_is_versioned_and_matches_existing_scoring():
    assert set(CATALOG) == {"DEMO_ANX_7", "DEMO_DEP_9"}
    for item in CATALOG.values():
        assert item.to_catalog()["demo_only"] is True
        assert len(item.questions) == (7 if item.test_id == "DEMO_ANX_7" else 9)
        assert item.version == "demo-1"
        assert "не валидирован" in item.to_catalog()["source"]
        definition(item.test_id)


def test_score_and_critical_rule_are_not_diagnoses():
    assert score("DEMO_DEP_9", "demo-1", [0] * 9) == (0, False)
    assert score("DEMO_DEP_9", "demo-1", [0] * 8 + [1]) == (1, True)
    assert score("DEMO_ANX_7", "demo-1", [3] * 7) == (21, False)
    with pytest.raises(ValueError):
        score("DEMO_DEP_9", "future", [0] * 9)
    with pytest.raises(ValueError):
        definition("PHQ-9")


def test_strict_inputs_reject_booleans_strings_and_partial():
    with pytest.raises(ValidationError):
        SubmitDemoTest(expected_revision=1, answers=[True] * 9)
    with pytest.raises(ValidationError):
        SubmitDemoTest(expected_revision=1, answers=["1"] * 9)
    with pytest.raises(ValidationError):
        SubmitDemoTest(expected_revision=0, answers=[0] * 9)
    with pytest.raises(ValueError):
        score("DEMO_DEP_9", "demo-1", [0] * 8)
    with pytest.raises(ValueError):
        score("DEMO_DEP_9", "demo-1", [4] * 9)
    with pytest.raises(ValidationError):
        AssignDemoTest(test_id="GAD-7", request_key="4fa22a07-0000-4000-8000-000000000001")
