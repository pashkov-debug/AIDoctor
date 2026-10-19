"""6.3.3: CLI всегда использует EICAR-гейт; без БД и сетевых вызовов."""

import sys
from types import SimpleNamespace

import pytest
from app.services.attachment_av_policy import PreflightGatedScanner
from app.workers import attachment_clamd_once as cli


class FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_cli_uses_preflight_gated_scanner(monkeypatch, capsys):
    monkeypatch.setattr(cli, "settings", SimpleNamespace(
        attachment_clamd_enabled=True,
        attachments_dir="unused",
    ))
    monkeypatch.setattr(cli, "SessionLocal", FakeSession)
    monkeypatch.setattr(cli, "AttachmentStorage", lambda _path: object())
    monkeypatch.setattr(cli, "ClamdScanner", lambda: object())

    def fake_scan(_session, **kwargs):
        assert isinstance(kwargs["scanner"], PreflightGatedScanner)
        assert kwargs["patient_id"] == "synthetic-patient"
        assert kwargs["actor_id"] == "synthetic-admin"
        return SimpleNamespace(status="error", id="fake")

    monkeypatch.setattr(cli, "scan_quarantined_attachment", fake_scan)
    monkeypatch.setattr(
        sys, "argv",
        ["run", "--once", "--patient-id", "synthetic-patient",
         "--attachment-id", "synthetic-document", "--actor-id", "synthetic-admin"],
    )
    assert cli.main() == 1
    assert "карантин сохранён" in capsys.readouterr().out


@pytest.mark.parametrize("enable,once", [(False, True), (True, False)])
def test_cli_refuses_without_explicit_enable(monkeypatch, enable, once):
    monkeypatch.setattr(cli, "settings", SimpleNamespace(attachment_clamd_enabled=enable))
    monkeypatch.setattr(
        sys, "argv",
        ["run", *(["--once"] if once else []),
         "--patient-id", "p", "--attachment-id", "a", "--actor-id", "u"],
    )
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
