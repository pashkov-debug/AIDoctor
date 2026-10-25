"""Этап 3: проверка точности учебного кейса без подключения к БД."""

from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.scripts.seed_aviandr_case import (
    SOURCE_KEY,
    _history_specs,
    _observation_specs,
    load_case,
    require_safe_target,
)


def test_document_has_complete_8_week_timeline() -> None:
    case = load_case()
    assert case["seed_key"] == SOURCE_KEY
    assert case["patient"]["demographics"]["synthetic"] is True
    assert case["patient"]["demographics"]["demo_featured"] is True
    assert len(case["weekly_visits"]) == 9
    assert len(case["patient_diary"]) == 10
    assert [p["date"] for p in case["dynamics"]] == [
        (date(2026, 8, 3) + timedelta(weeks=n)).isoformat() for n in range(9)
    ]
    assert [p["GAD-7"] for p in case["dynamics"]] == [17, 15, 13, 11, 10, 9, 8, 7, 6]
    assert case["dynamics"][0]["HAM-A"] == 27
    assert case["dynamics"][-1]["HAM-A"] == 11
    assert case["dynamics"][0]["ISI"] == 17
    assert case["dynamics"][-1]["ISI"] == 8
    assert case["dynamics"][-1]["PHQ-9"] == 2
    assert case["dynamics"][-1]["sleep_hours"] == pytest.approx(7.1)


def test_prepared_observations_not_fake_questionnaire_answers() -> None:
    case = load_case()
    only_start = _observation_specs(case, 0)
    all_weeks = _observation_specs(case, 8)
    assert len(only_start) == 18
    assert len(all_weeks) == 72
    assert all(x["day"] <= "2026-08-03" for x in only_start)
    assert any(x["system"] == "historical-clinical-scale" for x in all_weeks)
    assert not any("item_scores" in x["value"] for x in all_weeks)
    assert not any(x["system"] == "DEMO_ANX_7" for x in all_weeks)
    assert len({x["key"] for x in all_weeks}) == len(all_weeks)


def test_historical_entries_progress_without_future_data() -> None:
    case = load_case()
    start = _history_specs(case, 0)
    end = _history_specs(case, 8)
    assert len(start) == 12
    assert len(end) == 44
    assert all(x["date"] == "2026-08-03" for x in start)
    assert any(x["section"] == "Самостоятельный дневник пациента" for x in end)
    assert any("v3" in x["text"] for x in end)
    assert len({x["key"] for x in end}) == len(end)


def test_medication_plan_is_unapproved_without_invented_times() -> None:
    case = load_case()
    med = case["clinical_order_draft"]
    assert med["dose_value"] == "20"
    assert med["frequency_per_day"] == 2
    assert med["times_local"] is None
    assert med["duration_days"] is None
    assert med["strength"] is None
    assert med["start_date"] == "2026-08-03"


@pytest.mark.parametrize(
    ("environment", "url", "actual"),
    [
        (
            "production",
            "postgresql+psycopg://a:p@postgres/aidoctor_synthetic",
            "aidoctor_synthetic",
        ),
        ("local", "postgresql+psycopg://a:p@postgres/aidoctor_synthetic", "aidoctor_synthetic"),
        ("test", "postgresql+psycopg://a:p@postgres/aidoctor", "aidoctor"),
        ("test", "postgresql+psycopg://a:p@postgres/aidoctor_synthetic", "another"),
    ],
)
def test_seed_rejects_unsafe_databases(environment, url, actual) -> None:
    with pytest.raises(ValueError, match="aidoctor_synthetic"):
        require_safe_target(environment, url, actual)


def test_seed_allows_explicit_test_database() -> None:
    require_safe_target(
        "test", "postgresql+psycopg://a:p@postgres/aidoctor_synthetic", "aidoctor_synthetic"
    )


def test_dockerfile_includes_fixture_without_automatic_seeding() -> None:
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "deploy/Dockerfile.test").read_text(encoding="utf-8")
    assert "COPY backend/demo_cases ./backend/demo_cases" in dockerfile
    compose = (root / "deploy/compose.test.yaml").read_text(encoding="utf-8")
    assert "seed_aviandr_case" not in compose
