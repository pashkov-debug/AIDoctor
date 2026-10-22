"""6.3.1: ТОЛЬКО симуляция протокола, не доказательство реального AV."""

import socket
import struct

import pytest
from app.services.attachment_clamd import ClamdScanner, ClamdUnavailable
from app.services.attachment_storage import MAX_FILE_BYTES


class SimulatedSocket:
    def __init__(self, response):
        self.response = bytearray(response)
        self.writes = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def settimeout(self, _timeout):
        pass

    def sendall(self, payload):
        self.writes.extend(payload)

    def recv(self, _size):
        return bytes((self.response.pop(0),)) if self.response else b""


def simulated(monkeypatch, scan_response, version=b"ClamAV synthetic-test\x00"):
    sock1 = SimulatedSocket(scan_response)
    sock2 = SimulatedSocket(version)
    queue = iter((sock1, sock2))
    addresses = []

    def connect(address, timeout):
        addresses.append((address, timeout))
        return next(queue)

    monkeypatch.setattr(socket, "create_connection", connect)
    return sock1, sock2, addresses


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        (b"stream: OK\x00", "clean_reported"),
        (b"stream: Eicar-Test-Signature FOUND\x00", "infected_reported"),
    ],
)
def test_instream_protocol_reports_verdict_without_release(monkeypatch, reply, expected):
    first, second, addresses = simulated(monkeypatch, reply)
    payload = b"%PDF-1.7\nSYNTHETIC-DATA"
    result = ClamdScanner().scan(payload)
    assert result.status == expected
    assert result.engine_version.startswith("ClamAV ")
    assert first.writes == (
        b"zINSTREAM\x00" + struct.pack(">I", len(payload)) + payload + b"\x00" * 4
    )
    assert second.writes == b"zVERSION\x00"
    assert addresses == [(("127.0.0.1", 3310), 60.0)] * 2


@pytest.mark.parametrize(
    "reply",
    [
        b"stream: malformed\x00",
        b"stream: OK\\n",
        b"stream: ERROR\x00",
        b"stream: INSTREAM size limit exceeded. ERROR\x00",
        b"",
    ],
)
def test_unknown_or_incomplete_reply_fails_closed(monkeypatch, reply):
    simulated(monkeypatch, reply)
    with pytest.raises(ClamdUnavailable):
        ClamdScanner().scan(b"%PDF-1.7")


def test_missing_version_fails_closed(monkeypatch):
    simulated(monkeypatch, b"stream: OK\x00", version=b"unknown\x00")
    with pytest.raises(ClamdUnavailable):
        ClamdScanner().scan(b"%PDF-1.7")


def test_network_failure_fails_closed(monkeypatch):
    def fail(_address, _timeout):
        raise TimeoutError("timeout")

    monkeypatch.setattr(socket, "create_connection", fail)
    with pytest.raises(ClamdUnavailable):
        ClamdScanner().scan(b"%PDF-1.7")


@pytest.mark.parametrize(
    "payload_size",
    [0, MAX_FILE_BYTES + 1],
    ids=["empty", "over-limit"],
)
def test_rejects_invalid_payload_size_without_network(monkeypatch, payload_size):
    # Не помещаем мегабайты в параметры pytest: на Windows pytest сохраняет
    # идентификатор текущего теста в PYTEST_CURRENT_TEST (лимит 32767 символов).
    def unexpected_connection(*_args, **_kwargs):
        pytest.fail("Размер должен проверяться до обращения к сети")

    monkeypatch.setattr(socket, "create_connection", unexpected_connection)
    with pytest.raises(ValueError):
        ClamdScanner().scan(b"x" * payload_size)


@pytest.mark.parametrize("port,timeout", [(0, 30), (70000, 30), (3310, 0), (3310, 121)])
def test_bounded_endpoint_configuration(port, timeout):
    with pytest.raises(ValueError):
        ClamdScanner(port=port, timeout=timeout)
