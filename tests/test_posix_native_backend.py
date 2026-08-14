# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import sys
import time

import pytest

from verselatch_app.backend import EvidenceRequest
from verselatch_app.model import ModelRequirement
from verselatch_app.session import SourceIdentity
from verselatch_platform import (
    PosixNativeBackendCancelled,
    PosixNativeBackendError,
    PosixNativeWorkerBackend,
)
from verselatch_platform.posix_files import PosixFileService, PosixModelService
import verselatch_platform.posix_backend as posix_backend


pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process adapter")


def _request(tmp_path: Path, *, audio_bytes: bytes = b"audio") -> tuple[EvidenceRequest, Path]:
    audio = tmp_path / "audio.wav"
    model = tmp_path / "ggml-large-v3-turbo.bin"
    audio.write_bytes(audio_bytes)
    model_bytes = b"model"
    model.write_bytes(model_bytes)

    files = PosixFileService()
    models = PosixModelService(str(model))
    requirement = ModelRequirement(
        name=model.name,
        size=len(model_bytes),
        sha256=hashlib.sha256(model_bytes).hexdigest(),
    )
    verification = models.verify(requirement)
    assert verification.ready
    return (
        EvidenceRequest(
            audio=files.identify_audio(str(audio)),
            language="auto",
            model=verification,
        ),
        audio,
    )


def _worker(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "verselatch-worker"
    path.write_text(
        f"#!{sys.executable}\n"
        "import json, os, signal, sys, time\n"
        + body,
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_backend_accepts_only_package_worker_name(tmp_path: Path) -> None:
    wrong = tmp_path / "arbitrary-tool"
    wrong.write_text("x", encoding="utf-8")
    wrong.chmod(wrong.stat().st_mode | stat.S_IXUSR)
    with pytest.raises(ValueError, match="unexpected executable name"):
        PosixNativeWorkerBackend(str(wrong))


def test_success_response_becomes_analysis_evidence(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        "request = json.loads(sys.stdin.read())\n"
        "with open(request['audio_ref'], 'rb') as handle:\n"
        "    assert handle.read() == b'audio'\n"
        "print(json.dumps({"
        "'protocol': 1, 'request_id': request['request_id'], 'type': 'analysis',"
        "'payload': {'segments': [{'start': 0.0, 'end': 1.0, 'text': 'hello'}], 'rhythm': {}}"
        "}, separators=(',', ':')))\n",
    )
    request, _ = _request(tmp_path)
    job = PosixNativeWorkerBackend(str(worker)).start(request)
    evidence = job.result(timeout=5)
    assert evidence.segments == ({"start": 0.0, "end": 1.0, "text": "hello"},)


def test_inherited_audio_fd_survives_path_replacement(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        "request = json.loads(sys.stdin.read())\n"
        "time.sleep(0.20)\n"
        "with open(request['audio_ref'], 'rb') as handle:\n"
        "    text = handle.read().decode('ascii')\n"
        "print(json.dumps({"
        "'protocol': 1, 'request_id': request['request_id'], 'type': 'analysis',"
        "'payload': {'segments': [{'start': 0.0, 'end': 1.0, 'text': text}], 'rhythm': {}}"
        "}, separators=(',', ':')))\n",
    )
    request, audio = _request(tmp_path, audio_bytes=b"original")
    files = PosixFileService()
    job = PosixNativeWorkerBackend(str(worker)).start(request)

    replacement = tmp_path / "replacement.wav"
    replacement.write_bytes(b"replacement")
    os.replace(replacement, audio)

    evidence = job.result(timeout=5)
    assert evidence.segments[0]["text"] == "original"
    assert not files.revalidate(request.audio)


def test_non_posix_audio_identity_is_rejected(tmp_path: Path) -> None:
    worker = _worker(tmp_path, "raise SystemExit(0)\n")
    request, _ = _request(tmp_path)
    forged = EvidenceRequest(
        audio=SourceIdentity(location=request.audio.location, revision=("forged",)),
        language=request.language,
        model=request.model,
    )
    with pytest.raises(PosixNativeBackendError, match="POSIX-verified audio"):
        PosixNativeWorkerBackend(str(worker)).start(forged)


def test_stale_audio_is_rejected_before_launch(tmp_path: Path) -> None:
    worker = _worker(tmp_path, "raise SystemExit(0)\n")
    request, audio = _request(tmp_path)
    audio.write_bytes(b"changed")
    with pytest.raises(PosixNativeBackendError, match="audio source changed"):
        PosixNativeWorkerBackend(str(worker)).start(request)


def test_stale_model_is_rejected_before_launch(tmp_path: Path) -> None:
    worker = _worker(tmp_path, "raise SystemExit(0)\n")
    request, _ = _request(tmp_path)
    Path(request.model.source.location).write_bytes(b"changed")
    with pytest.raises(PosixNativeBackendError, match="model changed"):
        PosixNativeWorkerBackend(str(worker)).start(request)


def test_unsafe_native_environment_is_stripped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LD_PRELOAD", "/tmp/verselatch-should-not-inherit.so")
    monkeypatch.setenv("PYTHONPATH", "/tmp/verselatch-should-not-inherit")
    worker = _worker(
        tmp_path,
        "request = json.loads(sys.stdin.read())\n"
        "clean = 'LD_PRELOAD' not in os.environ and 'PYTHONPATH' not in os.environ\n"
        "print(json.dumps({"
        "'protocol': 1, 'request_id': request['request_id'], 'type': 'analysis',"
        "'payload': {'segments': [{'start': 0.0, 'end': 1.0, 'text': str(clean)}], 'rhythm': {}}"
        "}, separators=(',', ':')))\n",
    )
    request, _ = _request(tmp_path)
    job = PosixNativeWorkerBackend(str(worker)).start(request)
    assert job.result(timeout=5).segments[0]["text"] == "True"


def test_stale_response_id_is_rejected(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        "request = json.loads(sys.stdin.read())\n"
        "print(json.dumps({"
        "'protocol': 1, 'request_id': request['request_id'] + 1, 'type': 'analysis',"
        "'payload': {'segments': [], 'rhythm': {}}"
        "}, separators=(',', ':')))\n",
    )
    request, _ = _request(tmp_path)
    job = PosixNativeWorkerBackend(str(worker)).start(request)
    with pytest.raises(PosixNativeBackendError, match="invalid response"):
        job.result(timeout=5)


def test_timeout_does_not_cancel_owned_job(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        "request = json.loads(sys.stdin.read())\n"
        "time.sleep(0.20)\n"
        "print(json.dumps({"
        "'protocol': 1, 'request_id': request['request_id'], 'type': 'analysis',"
        "'payload': {'segments': [], 'rhythm': {}}"
        "}, separators=(',', ':')))\n",
    )
    request, _ = _request(tmp_path)
    job = PosixNativeWorkerBackend(str(worker)).start(request)
    with pytest.raises(TimeoutError):
        job.result(timeout=0.01)
    assert job.result(timeout=5).segments == ()


def test_cancel_escalates_and_reaps_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(posix_backend, "CANCEL_GRACE_SECONDS", 0.05)
    worker = _worker(
        tmp_path,
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "sys.stdin.read()\n"
        "while True:\n"
        "    time.sleep(1)\n",
    )
    request, _ = _request(tmp_path)
    job = PosixNativeWorkerBackend(str(worker)).start(request)
    time.sleep(0.05)
    job.cancel()
    with pytest.raises(PosixNativeBackendCancelled):
        job.result(timeout=5)
    assert job._process.poll() is not None


def test_stdout_limit_is_enforced_while_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(posix_backend.worker_protocol, "MAX_RESPONSE_BYTES", 128)
    worker = _worker(
        tmp_path,
        "sys.stdin.read()\n"
        "sys.stdout.write('x' * 4096)\n"
        "sys.stdout.flush()\n"
        "time.sleep(10)\n",
    )
    request, _ = _request(tmp_path)
    job = PosixNativeWorkerBackend(str(worker)).start(request)
    with pytest.raises(PosixNativeBackendError, match="response exceeded size limit"):
        job.result(timeout=5)
    assert job._process.poll() is not None


def test_worker_error_envelope_is_not_treated_as_success(tmp_path: Path) -> None:
    worker = _worker(
        tmp_path,
        "request = json.loads(sys.stdin.read())\n"
        "print(json.dumps({"
        "'protocol': 1, 'request_id': request['request_id'], 'type': 'error',"
        "'code': 'INVALID_MODEL', 'message': 'model rejected'"
        "}, separators=(',', ':')))\n"
        "raise SystemExit(3)\n",
    )
    request, _ = _request(tmp_path)
    job = PosixNativeWorkerBackend(str(worker)).start(request)
    with pytest.raises(PosixNativeBackendError, match="INVALID_MODEL"):
        job.result(timeout=5)
