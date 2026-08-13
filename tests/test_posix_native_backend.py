# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
from pathlib import Path
import stat
import time

import pytest

from verselatch_app.backend import EvidenceRequest
from verselatch_app.model import ModelRequirement, ModelVerification
from verselatch_app.session import SourceIdentity
from verselatch_platform import (
    PosixNativeBackendCancelled,
    PosixNativeBackendError,
    PosixNativeWorkerBackend,
)
import verselatch_platform.posix_backend as posix_backend


pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process adapter")


def _identity(path: Path) -> SourceIdentity:
    return SourceIdentity(location=str(path), revision=("fixture", str(path)))


def _request(tmp_path: Path) -> EvidenceRequest:
    audio = tmp_path / "audio.wav"
    model = tmp_path / "ggml-large-v3-turbo.bin"
    audio.write_bytes(b"a")
    model.write_bytes(b"m")

    requirement = ModelRequirement(name=model.name, size=1, sha256="00")
    verification = ModelVerification(
        requirement=requirement,
        source=_identity(model),
        actual_name=model.name,
        actual_size=1,
        actual_sha256="00",
    )
    assert verification.ready
    return EvidenceRequest(audio=_identity(audio), language="auto", model=verification)


def _worker(tmp_path: Path, shell_body: str) -> Path:
    path = tmp_path / "verselatch-worker"
    path.write_text("#!/bin/sh\nset -eu\n" + shell_body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_backend_rejects_arbitrary_executable_name(tmp_path: Path) -> None:
    wrong = tmp_path / "arbitrary-tool"
    wrong.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    wrong.chmod(wrong.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(ValueError, match="unexpected executable name"):
        PosixNativeWorkerBackend(str(wrong))


def test_success_response_becomes_evidence(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        "cat >/dev/null\n"
        "printf '%s\\n' "
        "'{\"protocol\":1,\"request_id\":1,\"type\":\"analysis\","
        "\"payload\":{\"segments\":[{\"start\":0.0,\"end\":1.0,\"text\":\"hello\"}],"
        "\"rhythm\":{}}}'\n",
    )
    job = PosixNativeWorkerBackend(str(worker)).start(_request(tmp_path))
    evidence = job.result(timeout=5)
    assert evidence.segments == ({"start": 0.0, "end": 1.0, "text": "hello"},)
    assert evidence.beats == ()
    assert evidence.onsets == ()


def test_empty_segments_remain_valid_no_speech_success(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        "cat >/dev/null\n"
        "printf '%s\\n' "
        "'{\"protocol\":1,\"request_id\":1,\"type\":\"analysis\","
        "\"payload\":{\"segments\":[],\"rhythm\":{}}}'\n",
    )
    job = PosixNativeWorkerBackend(str(worker)).start(_request(tmp_path))
    assert job.result(timeout=5).segments == ()


def test_stale_response_id_is_rejected(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        "cat >/dev/null\n"
        "printf '%s\\n' "
        "'{\"protocol\":1,\"request_id\":2,\"type\":\"analysis\","
        "\"payload\":{\"segments\":[],\"rhythm\":{}}}'\n",
    )
    job = PosixNativeWorkerBackend(str(worker)).start(_request(tmp_path))
    with pytest.raises(PosixNativeBackendError, match="invalid response"):
        job.result(timeout=5)


def test_result_timeout_does_not_cancel_job(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        "cat >/dev/null\n"
        "sleep 0.2\n"
        "printf '%s\\n' "
        "'{\"protocol\":1,\"request_id\":1,\"type\":\"analysis\","
        "\"payload\":{\"segments\":[],\"rhythm\":{}}}'\n",
    )
    job = PosixNativeWorkerBackend(str(worker)).start(_request(tmp_path))
    with pytest.raises(TimeoutError):
        job.result(timeout=0.01)
    assert job.result(timeout=5).segments == ()


def test_cancel_terminates_process_group_and_reaps_direct_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(posix_backend, "CANCEL_GRACE_SECONDS", 0.05)
    worker = _worker(
        tmp_path,
        "trap '' TERM\n"
        "cat >/dev/null\n"
        "sleep 10\n",
    )
    job = PosixNativeWorkerBackend(str(worker)).start(_request(tmp_path))
    time.sleep(0.05)
    job.cancel()
    with pytest.raises(PosixNativeBackendCancelled):
        job.result(timeout=5)
    assert job._process.poll() is not None


def test_cancel_after_completion_does_not_destroy_completed_result(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        "cat >/dev/null\n"
        "printf '%s\\n' "
        "'{\"protocol\":1,\"request_id\":1,\"type\":\"analysis\","
        "\"payload\":{\"segments\":[],\"rhythm\":{}}}'\n",
    )
    job = PosixNativeWorkerBackend(str(worker)).start(_request(tmp_path))
    assert job.result(timeout=5).segments == ()
    job.cancel()
    assert job.result(timeout=0).segments == ()


def test_stdout_limit_stops_worker_with_inherited_pipe_descendant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(posix_backend.worker_protocol, "MAX_RESPONSE_BYTES", 128)
    monkeypatch.setattr(posix_backend, "CANCEL_GRACE_SECONDS", 0.05)
    worker = _worker(
        tmp_path,
        "cat >/dev/null\n"
        "(sleep 10) &\n"
        "i=0\n"
        "while [ \"$i\" -lt 4096 ]; do printf x; i=$((i + 1)); done\n"
        "wait\n",
    )

    started = time.monotonic()
    job = PosixNativeWorkerBackend(str(worker)).start(_request(tmp_path))
    with pytest.raises(PosixNativeBackendError, match="response exceeded size limit"):
        job.result(timeout=5)
    assert time.monotonic() - started < 5
    assert job._process.poll() is not None


def test_stderr_is_bounded_but_drained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(posix_backend, "MAX_STDERR_BYTES", 128)
    worker = _worker(
        tmp_path,
        "cat >/dev/null\n"
        "i=0\n"
        "while [ \"$i\" -lt 4096 ]; do printf e >&2; i=$((i + 1)); done\n"
        "printf '%s\\n' "
        "'{\"protocol\":1,\"request_id\":1,\"type\":\"analysis\","
        "\"payload\":{\"segments\":[],\"rhythm\":{}}}'\n",
    )

    job = PosixNativeWorkerBackend(str(worker)).start(_request(tmp_path))
    assert job.result(timeout=5).segments == ()
    assert job._stderr.overflow
    assert len(job._stderr.data) == 128


def test_worker_error_envelope_is_not_success(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        "cat >/dev/null\n"
        "printf '%s\\n' "
        "'{\"protocol\":1,\"request_id\":1,\"type\":\"error\","
        "\"code\":\"INVALID_MODEL\",\"message\":\"model rejected\"}'\n"
        "exit 3\n",
    )

    job = PosixNativeWorkerBackend(str(worker)).start(_request(tmp_path))
    with pytest.raises(PosixNativeBackendError, match="INVALID_MODEL"):
        job.result(timeout=5)
