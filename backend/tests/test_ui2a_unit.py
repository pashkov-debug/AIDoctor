"""UI-2A: ограничения локального seed и границы демонстрационных записей."""
from datetime import UTC, datetime

import pytest

from backend.scripts.seed_ui2a_synthetic import (
    EVENTS,
    OBSERVATIONS,
    VISITS,
    ensure_local_development_target,
)


def test_seed_only_local_development_database() -> None:
    url = "postgresql+psycopg://aidoctor:secret@127.0.0.1:5432/aidoctor"
    ensure_local_development_target("local", url, "aidoctor")
    for env, location, name in (
        ("production", url, "aidoctor"),
        ("test", url, "aidoctor"),
        ("local", url, "aidoctor_test"),
        ("local", url.replace("/aidoctor", "/aidoctor_test"), "aidoctor_test"),
        ("local", url.replace("127.0.0.1", "db.internal"), "aidoctor"),
    ):
        with pytest.raises(ValueError, match="Seed"):
            ensure_local_development_target(env, location, name)


def test_seed_contains_only_tagged_subjective_demo_data() -> None:
    assert len(VISITS) == 4
    assert len(EVENTS) == 6
    assert len(OBSERVATIONS) == 3
    assert min(item[0] for item in VISITS) <= -30
    assert all(item[0] <= 0 for item in VISITS + EVENTS + OBSERVATIONS)
    assert datetime.now(UTC).tzinfo is UTC
