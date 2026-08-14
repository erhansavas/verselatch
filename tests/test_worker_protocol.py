# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

import json

import pytest

from verselatch_app import worker_protocol
from verselatch_app.worker_protocol import (
    PROTOCOL_VERSION,
    WorkerProtocolError,
    WorkerRequest,
    decode_response,
    encode_request,
)


def response_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def test_request_encoding_is_deterministic_and_unicode_safe() -> None:
    request = WorkerRequest(
        request_id=7,
        audio_ref="app-private://audio/şarkı.flac",
        model_ref="app-private://models/large.bin",
        language="tr",
        lyrics="birinci satır\n",
    )
    first = encode_request(request)
    second = encode_request(request)
    assert first == second
    assert first.decode("utf-8").startswith('{"audio_ref":')
    parsed = json.loads(first)
    assert parsed["protocol"] == PROTOCOL_VERSION
    assert parsed["type"] == "analyze"
    assert parsed["request_id"] == 7


def test_request_rejects_invalid_identity_and_nul() -> None:
    with pytest.raises(WorkerProtocolError, match="request id"):
        encode_request(WorkerRequest(0, "audio", "model", "auto", None))
    with pytest.raises(WorkerProtocolError, match="audio reference"):
        encode_request(WorkerRequest(1, "bad\x00audio", "model", "auto", None))
    with pytest.raises(WorkerProtocolError, match="language"):
        encode_request(WorkerRequest(1, "audio", "model", "tr\x00", None))
    with pytest.raises(WorkerProtocolError, match="lyrics"):
        encode_request(WorkerRequest(1, "audio", "model", "auto", "bad\x00lyrics"))


def test_request_size_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_protocol, "MAX_REQUEST_BYTES", 64)
    with pytest.raises(WorkerProtocolError, match="size limit"):
        encode_request(WorkerRequest(1, "audio", "model", "auto", "x" * 128))


def test_success_response_requires_exact_envelope_and_request_id() -> None:
    payload = {"segments": [], "rhythm": {}}
    data = response_bytes(
        {
            "payload": payload,
            "protocol": PROTOCOL_VERSION,
            "request_id": 9,
            "type": "analysis",
        }
    )
    response = decode_response(data, expected_request_id=9)
    assert response.ok is True
    assert response.payload == payload

    with pytest.raises(WorkerProtocolError, match="stale"):
        decode_response(data, expected_request_id=10)


def test_response_rejects_unknown_fields_and_wrong_version() -> None:
    with pytest.raises(WorkerProtocolError, match="unexpected"):
        decode_response(
            response_bytes(
                {
                    "payload": {},
                    "protocol": PROTOCOL_VERSION,
                    "request_id": 1,
                    "type": "analysis",
                    "surprise": True,
                }
            ),
            expected_request_id=1,
        )

    with pytest.raises(WorkerProtocolError, match="version"):
        decode_response(
            response_bytes(
                {
                    "payload": {},
                    "protocol": PROTOCOL_VERSION + 1,
                    "request_id": 1,
                    "type": "analysis",
                }
            ),
            expected_request_id=1,
        )


def test_typed_error_response_is_strict() -> None:
    response = decode_response(
        response_bytes(
            {
                "code": "AUDIO_DECODE_FAILED",
                "message": "decoder rejected input",
                "protocol": PROTOCOL_VERSION,
                "request_id": 4,
                "type": "error",
            }
        ),
        expected_request_id=4,
    )
    assert response.ok is False
    assert response.error_code == "AUDIO_DECODE_FAILED"

    with pytest.raises(WorkerProtocolError, match="error code"):
        decode_response(
            response_bytes(
                {
                    "code": "SHELL_COMMAND",
                    "message": "unexpected",
                    "protocol": PROTOCOL_VERSION,
                    "request_id": 4,
                    "type": "error",
                }
            ),
            expected_request_id=4,
        )


def test_response_rejects_malformed_encoding_and_json() -> None:
    with pytest.raises(WorkerProtocolError, match="UTF-8"):
        decode_response(b"\xff", expected_request_id=1)
    with pytest.raises(WorkerProtocolError, match="valid bounded JSON"):
        decode_response(b"{", expected_request_id=1)
    with pytest.raises(WorkerProtocolError, match="root"):
        decode_response(b"[]", expected_request_id=1)


def test_response_rejects_ambiguous_or_nonfinite_json() -> None:
    duplicate = (
        b'{"payload":{},"protocol":1,"request_id":1,'
        b'"request_id":1,"type":"analysis"}'
    )
    with pytest.raises(WorkerProtocolError, match="duplicate"):
        decode_response(duplicate, expected_request_id=1)

    nonfinite = (
        b'{"payload":{"score":NaN},"protocol":1,'
        b'"request_id":1,"type":"analysis"}'
    )
    with pytest.raises(WorkerProtocolError, match="non-finite"):
        decode_response(nonfinite, expected_request_id=1)

    huge_integer = (
        b'{"payload":{"value":123456789012345678901},"protocol":1,'
        b'"request_id":1,"type":"analysis"}'
    )
    with pytest.raises(WorkerProtocolError, match="out of bounds"):
        decode_response(huge_integer, expected_request_id=1)


def test_response_size_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_protocol, "MAX_RESPONSE_BYTES", 8)
    with pytest.raises(WorkerProtocolError, match="size limit"):
        decode_response(b"123456789", expected_request_id=1)
