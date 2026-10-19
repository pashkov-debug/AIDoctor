"""6.3.3: fail-closed AV-гейт, только синтетические байты; без сети и БД."""

from datetime import UTC, datetime

import pytest
from app.services.attachment_av_policy import PreflightGatedScanner
from app.services.attachment_clamd import ClamdUnavailable, ClamdVerdict
from app.services.clamd_health import eicar_bytes

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
VERSION = "ClamAV 1.5.4/28400/Mon Oct 19 11:00:00 2026"
STALE = "ClamAV 1.5.4/28000/Thu Oct 01 11:00:00 2026"
CHANGED = "ClamAV 1.5.5/28401/Mon Oct 19 11:10:00 2026"
PAYLOAD = b"%PDF-1.7\nSYNTHETIC-ONLY"


class ScriptedScanner:
    def __init__(self, *events):
        self.events = list(events)
        self.seen = []

    def scan(self, payload):
        self.seen.append(payload)
        if not self.events:
            pytest.fail("Неожиданный дополнительный вызов сканера")
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event


def av(status, version=VERSION):
    return ClamdVerdict(status, version)


def gated(scanner):
    return PreflightGatedScanner(scanner, clock=lambda: NOW)


def test_clean_is_returned_only_after_two_eicar_checks_with_same_version():
    scanner = ScriptedScanner(
        av("infected_reported"), av("clean_reported"), av("infected_reported")
    )
    result = gated(scanner).scan(PAYLOAD)
    assert result.status == "clean_reported"
    assert scanner.seen == [eicar_bytes(), PAYLOAD, eicar_bytes()]
    assert scanner.events == []


@pytest.mark.parametrize("status", ["clean_reported", "error", "unknown"])
def test_failed_eicar_never_sends_medical_bytes(status):
    scanner = ScriptedScanner(av(status))
    with pytest.raises(ClamdUnavailable):
        gated(scanner).scan(PAYLOAD)
    assert scanner.seen == [eicar_bytes()]


def test_stale_signatures_prevent_medical_transfer():
    scanner = ScriptedScanner(av("infected_reported", STALE))
    with pytest.raises(ClamdUnavailable):
        gated(scanner).scan(PAYLOAD)
    assert scanner.seen == [eicar_bytes()]


def test_offline_before_scan_prevents_medical_transfer():
    scanner = ScriptedScanner(ClamdUnavailable("offline"))
    with pytest.raises(ClamdUnavailable):
        gated(scanner).scan(PAYLOAD)
    assert scanner.seen == [eicar_bytes()]


def test_version_changed_during_scan_rejects_clean():
    scanner = ScriptedScanner(av("infected_reported"), av("clean_reported", CHANGED))
    with pytest.raises(ClamdUnavailable, match="изменилась"):
        gated(scanner).scan(PAYLOAD)
    assert scanner.seen == [eicar_bytes(), PAYLOAD]


def test_version_changed_after_scan_rejects_clean():
    scanner = ScriptedScanner(
        av("infected_reported"), av("clean_reported"), av("infected_reported", CHANGED)
    )
    with pytest.raises(ClamdUnavailable, match="изменилась"):
        gated(scanner).scan(PAYLOAD)
    assert scanner.seen == [eicar_bytes(), PAYLOAD, eicar_bytes()]


@pytest.mark.parametrize("result", ["clean_reported", "error", "unknown"])
def test_failed_second_eicar_rejects_clean(result):
    scanner = ScriptedScanner(av("infected_reported"), av("clean_reported"), av(result))
    with pytest.raises(ClamdUnavailable):
        gated(scanner).scan(PAYLOAD)
    assert scanner.seen == [eicar_bytes(), PAYLOAD, eicar_bytes()]


def test_failed_second_eicar_transport_rejects_clean():
    scanner = ScriptedScanner(
        av("infected_reported"), av("clean_reported"), ClamdUnavailable("offline")
    )
    with pytest.raises(ClamdUnavailable):
        gated(scanner).scan(PAYLOAD)
    assert scanner.seen == [eicar_bytes(), PAYLOAD, eicar_bytes()]


def test_positive_detection_is_not_silenced_by_absence_of_postflight():
    scanner = ScriptedScanner(av("infected_reported"), av("infected_reported"))
    assert gated(scanner).scan(PAYLOAD).status == "infected_reported"
    assert scanner.seen == [eicar_bytes(), PAYLOAD]


def test_unexpected_scan_result_fails_closed():
    scanner = ScriptedScanner(av("infected_reported"), av("error"))
    with pytest.raises(ClamdUnavailable, match="Неизвестный"):
        gated(scanner).scan(PAYLOAD)


@pytest.mark.parametrize("content", [b"", "not-bytes", None])
def test_invalid_payload_never_contacts_scanner(content):
    scanner = ScriptedScanner()
    with pytest.raises(ValueError):
        gated(scanner).scan(content)
    assert scanner.seen == []


@pytest.mark.parametrize("days", [0, 31])
def test_invalid_max_age_rejected_on_creation(days):
    with pytest.raises(ValueError):
        PreflightGatedScanner(ScriptedScanner(), max_db_age_days=days)


def test_original_processing_gate_stays_closed():
    from app.services.attachment_security import ProcessingProhibited, require_processing_clearance

    with pytest.raises(ProcessingProhibited):
        require_processing_clearance(None, None)
