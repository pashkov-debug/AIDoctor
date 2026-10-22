"""Негативные сценарии проверки готовности AV; сеть/реальный clamd не нужны."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from app.services.attachment_clamd import ClamdUnavailable, ClamdVerdict
from app.workers import clamd_preflight as pf

NOW = datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
VERSION = "ClamAV 1.5.4/28400/Mon Oct 19 11:00:00 2026"


class FakeScanner:
    def __init__(self, verdict=None, exc=None):
        self.verdict = verdict or ClamdVerdict("infected_reported", VERSION)
        self.exc = exc
        self.calls = []

    def scan(self, content):
        self.calls.append(content)
        if self.exc:
            raise self.exc
        return self.verdict


def test_eicar_has_correct_bytes_without_any_file_write():
    payload = pf.eicar_bytes()
    assert len(payload) == 68
    # Константная контрольная сумма исключает непреднамеренную порчу сигнатуры.
    assert sha256(payload).hexdigest() == (
        "275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f"
    )


def test_eicar_detected_and_version_fresh():
    scanner = FakeScanner()
    checked = pf.verify_clamd(scanner, now=NOW)
    assert checked == datetime(2026, 10, 19, 11, tzinfo=UTC)
    assert scanner.calls == [pf.eicar_bytes()]


@pytest.mark.parametrize(
    "status",
    ["clean_reported", "error", "unknown", ""],
)
def test_absent_detection_fails_closed(status):
    scanner = FakeScanner(ClamdVerdict(status, VERSION))
    with pytest.raises(pf.PreflightFailure, match="не распознал"):
        pf.verify_clamd(scanner, now=NOW)


def test_transport_unavailable_fails_closed():
    scanner = FakeScanner(exc=ClamdUnavailable("closed"))
    with pytest.raises(pf.PreflightFailure, match="Нет законченного"):
        pf.verify_clamd(scanner, now=NOW)


@pytest.mark.parametrize(
    "version",
    [
        "ClamAV synthetic-test",
        "ClamAV 1.5.4/0/Mon Oct 19 11:00:00 2026",
        "ClamAV 1.5.4/28400/garbage",
        "not-clamd",
        "",
    ],
)
def test_unverifiable_version_fails_closed(version):
    with pytest.raises(pf.PreflightFailure):
        pf.validate_signature_date(version, now=NOW)


def test_stale_signature_database_fails_closed():
    stale = "ClamAV 1.5.4/28400/Thu Oct 01 11:00:00 2026"
    with pytest.raises(pf.PreflightFailure, match="устарела"):
        pf.validate_signature_date(stale, now=NOW)


def test_future_timestamp_fails_closed():
    future = "ClamAV 1.5.4/28400/Fri Oct 23 11:00:00 2026"
    with pytest.raises(pf.PreflightFailure, match="будущем"):
        pf.validate_signature_date(future, now=NOW)


def test_timezone_aware_required_for_injected_clock():
    with pytest.raises(ValueError, match="timezone-aware"):
        pf.validate_signature_date(VERSION, now=datetime(2026, 10, 19))


def test_age_limit_boundary():
    current = datetime(2026, 10, 19, 11, tzinfo=UTC)
    assert pf.validate_signature_date(VERSION, now=current + timedelta(days=7)) == current
    with pytest.raises(pf.PreflightFailure, match="устарела"):
        pf.validate_signature_date(VERSION, now=current + timedelta(days=7, seconds=1))


@pytest.mark.parametrize("days", [0, 31])
def test_invalid_allowed_age(days):
    with pytest.raises(ValueError):
        pf.validate_signature_date(VERSION, now=NOW, max_age_days=days)


def test_cli_requires_explicit_consent():
    with pytest.raises(SystemExit) as exc:
        pf.main([])
    assert exc.value.code == 2


def test_cli_no_real_network(monkeypatch, capsys):
    monkeypatch.setattr(pf, "ClamdScanner", FakeScanner)
    monkeypatch.setattr(pf, "verify_clamd", lambda _scanner, max_age_days: NOW)
    assert pf.main(["--check-eicar"]) == 0
    assert "не допуск вложений" in capsys.readouterr().out


def test_cli_fails_without_detection(monkeypatch, capsys):
    monkeypatch.setattr(
        pf, "ClamdScanner", lambda: FakeScanner(ClamdVerdict("clean_reported", VERSION))
    )
    assert pf.main(["--check-eicar"]) == 1
    assert "Карантин сохраняется" in capsys.readouterr().out


def test_no_automatic_release_contract():
    from app.services.attachment_security import ProcessingProhibited, require_processing_clearance

    with pytest.raises(ProcessingProhibited):
        require_processing_clearance(None, None)
