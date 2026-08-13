# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from dataclasses import dataclass
import json
import re


PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 5 * 1024 * 1024
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_RESOURCE_REF_CHARS = 4096
MAX_LANGUAGE_CHARS = 16
MAX_ERROR_MESSAGE_CHARS = 4096
ERROR_CODES = frozenset(
    {
        "CANCELLED",
        "INVALID_REQUEST",
        "INVALID_MODEL",
        "AUDIO_DECODE_FAILED",
        "ASR_FAILED",
        "RHYTHM_FAILED",
        "INTERNAL_ERROR",
    }
)
_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class WorkerProtocolError(ValueError):
    """The native worker message violated the bounded protocol contract."""


@dataclass(frozen=True)
class WorkerRequest:
    request_id: int
    audio_ref: str
    model_ref: str
    language: str
    lyrics: str | None


@dataclass(frozen=True)
class WorkerResponse:
    request_id: int
    payload: dict[str, object] | None
    error_code: str | None
    error_message: str | None

    @property
    def ok(self) -> bool:
        return self.error_code is None


def _valid_request_id(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < 2**63


def _validate_resource_ref(value: str, *, name: str) -> None:
    if not value or len(value) > MAX_RESOURCE_REF_CHARS or "\x00" in value:
        raise WorkerProtocolError(f"invalid {name}")


def encode_request(request: WorkerRequest) -> bytes:
    """Encode one deterministic worker request and enforce its input bounds."""
    if not _valid_request_id(request.request_id):
        raise WorkerProtocolError("invalid request id")
    _validate_resource_ref(request.audio_ref, name="audio reference")
    _validate_resource_ref(request.model_ref, name="model reference")
    if not request.language or len(request.language) > MAX_LANGUAGE_CHARS:
        raise WorkerProtocolError("invalid language")
    if request.lyrics is not None and "\x00" in request.lyrics:
        raise WorkerProtocolError("lyrics contain NUL")

    message = {
        "audio_ref": request.audio_ref,
        "language": request.language,
        "lyrics": request.lyrics,
        "model_ref": request.model_ref,
        "protocol": PROTOCOL_VERSION,
        "request_id": request.request_id,
        "type": "analyze",
    }
    encoded = json.dumps(
        message,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(encoded) > MAX_REQUEST_BYTES:
        raise WorkerProtocolError("worker request exceeds size limit")
    return encoded


def decode_response(data: bytes, *, expected_request_id: int) -> WorkerResponse:
    """Decode one complete bounded response and reject stale/malformed envelopes."""
    if not _valid_request_id(expected_request_id):
        raise WorkerProtocolError("invalid expected request id")
    if not data or len(data) > MAX_RESPONSE_BYTES:
        raise WorkerProtocolError("worker response exceeds size limit or is empty")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkerProtocolError("worker response is not UTF-8") from exc
    try:
        message = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WorkerProtocolError("worker response is not valid JSON") from exc
    if not isinstance(message, dict):
        raise WorkerProtocolError("worker response root must be an object")

    common = {"protocol", "request_id", "type"}
    if message.get("protocol") != PROTOCOL_VERSION:
        raise WorkerProtocolError("unsupported worker protocol version")
    request_id = message.get("request_id")
    if not _valid_request_id(request_id) or request_id != expected_request_id:
        raise WorkerProtocolError("stale or invalid worker response id")

    kind = message.get("type")
    if kind == "analysis":
        if set(message) != common | {"payload"}:
            raise WorkerProtocolError("unexpected analysis response fields")
        payload = message.get("payload")
        if not isinstance(payload, dict):
            raise WorkerProtocolError("analysis payload must be an object")
        return WorkerResponse(
            request_id=request_id,
            payload=payload,
            error_code=None,
            error_message=None,
        )

    if kind == "error":
        if set(message) != common | {"code", "message"}:
            raise WorkerProtocolError("unexpected error response fields")
        code = message.get("code")
        error_message = message.get("message")
        if (
            not isinstance(code, str)
            or code not in ERROR_CODES
            or _ERROR_CODE_RE.fullmatch(code) is None
        ):
            raise WorkerProtocolError("unknown worker error code")
        if (
            not isinstance(error_message, str)
            or not error_message
            or len(error_message) > MAX_ERROR_MESSAGE_CHARS
            or "\x00" in error_message
        ):
            raise WorkerProtocolError("invalid worker error message")
        return WorkerResponse(
            request_id=request_id,
            payload=None,
            error_code=code,
            error_message=error_message,
        )

    raise WorkerProtocolError("unknown worker response type")
