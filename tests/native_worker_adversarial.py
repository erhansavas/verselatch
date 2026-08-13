# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import json
import math
from pathlib import Path
import struct
import subprocess
import sys
import wave


def invoke(worker: Path, payload: bytes) -> tuple[int, dict[str, object]]:
    completed = subprocess.run(
        [str(worker)],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.returncode, json.loads(completed.stdout)


def require_error(
    worker: Path,
    payload: bytes,
    *,
    status: int,
    code: str,
    request_id: int,
) -> None:
    actual_status, response = invoke(worker, payload)
    assert actual_status == status, (actual_status, response)
    assert response.get("protocol") == 1, response
    assert response.get("request_id") == request_id, response
    assert response.get("type") == "error", response
    assert response.get("code") == code, response


def write_wav(path: Path) -> None:
    rate = 16000
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = bytearray()
        for index in range(rate):
            sample = int(8000 * math.sin(2 * math.pi * 440 * index / rate))
            frames.extend(struct.pack("<h", sample))
        handle.writeframes(frames)


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: native_worker_adversarial.py WORKER FIXTURE_DIR")
    worker = Path(sys.argv[1])
    fixture_dir = Path(sys.argv[2])
    fixture_dir.mkdir(parents=True, exist_ok=True)

    duplicate = (
        b'{"audio_ref":"/tmp/a","language":"auto","lyrics":null,'
        b'"model_ref":"/tmp/m","protocol":1,"request_id":42,'
        b'"request_id":42,"type":"analyze"}'
    )
    require_error(worker, duplicate, status=2, code="INVALID_REQUEST", request_id=42)

    lyrics = {
        "audio_ref": "/tmp/a",
        "language": "auto",
        "lyrics": "not allowed",
        "model_ref": "/tmp/m",
        "protocol": 1,
        "request_id": 43,
        "type": "analyze",
    }
    require_error(
        worker,
        json.dumps(lyrics, separators=(",", ":")).encode(),
        status=2,
        code="INVALID_REQUEST",
        request_id=43,
    )

    wav = fixture_dir / "tone.wav"
    write_wav(wav)
    dummy_model = fixture_dir / "dummy-model.bin"
    dummy_model.write_bytes(b"not a model")
    audio_link = fixture_dir / "audio-link.wav"
    model_link = fixture_dir / "model-link.bin"
    audio_link.symlink_to(wav)
    model_link.symlink_to(dummy_model)

    audio_request = {
        "audio_ref": str(audio_link),
        "language": "auto",
        "lyrics": None,
        "model_ref": str(dummy_model),
        "protocol": 1,
        "request_id": 44,
        "type": "analyze",
    }
    require_error(
        worker,
        json.dumps(audio_request, separators=(",", ":")).encode(),
        status=2,
        code="INVALID_REQUEST",
        request_id=44,
    )

    model_request = {
        "audio_ref": str(wav),
        "language": "auto",
        "lyrics": None,
        "model_ref": str(model_link),
        "protocol": 1,
        "request_id": 45,
        "type": "analyze",
    }
    require_error(
        worker,
        json.dumps(model_request, separators=(",", ":")).encode(),
        status=3,
        code="INVALID_MODEL",
        request_id=45,
    )

    print("Native worker adversarial protocol/path checks: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
