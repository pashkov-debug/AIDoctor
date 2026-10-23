"""Изолированные тесты HTTP-имитатора, без PostgreSQL и внешнего AI."""

import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from scripts.mock_ai_server import MockHandler, validate_envelope
from scripts.smoke_ai_connection import canonical_sha256, choose_patient


def sample_request() -> dict:
    return {
        "schema_version": "aidoctor.mock_connection.v1",
        "request_id": str(uuid4()),
        "context_sha256": "a" * 64,
        "context_schema": "ai_agent_context.v1",
        "synthetic_confirmed": True,
        "approved_count": 1,
        "draft_count": 2,
    }


def test_envelope_requires_only_technical_fields():
    sample = sample_request()
    assert validate_envelope(sample) == sample
    with pytest.raises(ValueError):
        validate_envelope({**sample, "patient_context": {"diagnosis": "NOT ALLOWED"}})
    with pytest.raises(ValueError):
        validate_envelope({**sample, "synthetic_confirmed": False})
    with pytest.raises(ValueError):
        validate_envelope({**sample, "approved_count": True})


def test_select_only_synthetic_patient():
    patients = [
        {"id": "a", "alias": "А", "demographics": {"synthetic": False}},
        {"id": "b", "alias": "Б", "demographics": {"synthetic": True}},
    ]
    assert choose_patient(patients)["id"] == "b"
    with pytest.raises(ValueError):
        choose_patient(patients, "a")


def test_checksum_is_canonical():
    assert canonical_sha256({"x": 1, "y": 2}) == canonical_sha256({"y": 2, "x": 1})


def test_real_local_http_round_trip():
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(base + "/health", timeout=3) as response:
            health = json.load(response)
        assert health["llm_connected"] is False

        request = sample_request()
        body = json.dumps(request).encode("utf-8")
        with urlopen(
            Request(
                base + "/v1/simulate",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            ),
            timeout=3,
        ) as response:
            receipt = json.load(response)
        assert receipt["delivery_confirmed"] is True
        assert receipt["received_context_sha256"] == request["context_sha256"]
        assert receipt["analysis_performed"] is False
        assert receipt["recommendations"] == []

        request["patient_context"] = {"medical": "REJECT"}
        with pytest.raises(HTTPError) as err:
            urlopen(
                Request(
                    base + "/v1/simulate",
                    data=json.dumps(request).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                ),
                timeout=3,
            )
        assert err.value.code == 422
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
