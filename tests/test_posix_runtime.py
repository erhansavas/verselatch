# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import stat
import sys

import pytest

from verselatch_app.model import ModelRequirement
from verselatch_platform import (
    PosixFileService,
    PosixModelService,
    PosixNativeWorkerBackend,
    PosixRuntime,
    create_posix_runtime,
)


pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX composition root")


def _worker(tmp_path: Path) -> Path:
    path = tmp_path / "verselatch-worker"
    path.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "request = json.loads(sys.stdin.read())\n"
        "response = {\n"
        "    'protocol': 1,\n"
        "    'request_id': request['request_id'],\n"
        "    'type': 'analysis',\n"
        "    'payload': {\n"
        "        'segments': [{'start': 0.0, 'end': 1.0, 'text': 'hello world'}],\n"
        "        'rhythm': {},\n"
        "    },\n"
        "}\n"
        "print(json.dumps(response, separators=(',', ':')))\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _model_requirement(model: Path) -> ModelRequirement:
    data = model.read_bytes()
    return ModelRequirement(
        name=model.name,
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def test_posix_runtime_wires_one_shared_workflow(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    model = tmp_path / "fixture-model.bin"
    model.write_bytes(b"model fixture")

    runtime = create_posix_runtime(
        worker_path=str(worker),
        model_path=str(model),
    )

    assert isinstance(runtime, PosixRuntime)
    assert isinstance(runtime.files, PosixFileService)
    assert isinstance(runtime.models, PosixModelService)
    assert isinstance(runtime.backend, PosixNativeWorkerBackend)
    assert runtime.analysis.state is runtime.state
    assert runtime.save.state is runtime.state
    assert runtime.analysis.files is runtime.files
    assert runtime.save.files is runtime.files
    assert runtime.analysis.backend is runtime.backend


def test_posix_runtime_real_controller_review_save_chain(tmp_path: Path) -> None:
    worker = _worker(tmp_path)
    model = tmp_path / "fixture-model.bin"
    model.write_bytes(b"model fixture")
    audio = tmp_path / "song.wav"
    audio.write_bytes(b"audio fixture")

    runtime = create_posix_runtime(
        worker_path=str(worker),
        model_path=str(model),
    )

    verification = runtime.verify_model(_model_requirement(model))
    assert verification.ready

    source = runtime.files.identify_audio(str(audio))
    runtime.analysis.set_sources(audio=source, lyrics=None)
    runtime.analysis.set_language("en")

    active = runtime.analysis.start(model=verification)
    assert active.run_id == runtime.state.active_run_id
    outcome = runtime.analysis.finish(timeout=5.0)

    assert outcome is not None
    assert runtime.state.result is not None
    assert "hello world" in runtime.state.preview
    assert not runtime.state.save_eligible

    runtime.state.confirm_review(True)
    assert runtime.state.save_eligible

    receipt = runtime.save.save()
    output = Path(receipt.output.location)
    assert output == audio.with_suffix(".lrc")
    assert output.read_text(encoding="utf-8") == runtime.state.preview.rstrip() + "\n"
    assert receipt.backup is None
