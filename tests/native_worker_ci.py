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


def run_checked(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def protocol_smoke(worker: Path) -> None:
    request = {
        "audio_ref": "/tmp/a",
        "language": "auto",
        "lyrics": None,
        "model_ref": "/tmp/m",
        "protocol": 1,
        "request_id": 41,
        "surprise": True,
        "type": "analyze",
    }
    completed = subprocess.run(
        [str(worker)],
        input=json.dumps(request, separators=(",", ":")).encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 2:
        raise AssertionError(f"unexpected protocol smoke exit: {completed.returncode}")
    response = json.loads(completed.stdout)
    expected = {
        "code": "INVALID_REQUEST",
        "message": "worker request fields are invalid or duplicated",
        "protocol": 1,
        "request_id": 41,
        "type": "error",
    }
    if response != expected:
        raise AssertionError(f"unexpected protocol response: {response!r}")
    print("Native worker protocol smoke: PASS")


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


def decoder_smoke(decoder: Path, fixture_dir: Path) -> None:
    fixture_dir.mkdir(parents=True, exist_ok=True)
    wav = fixture_dir / "tone.wav"
    write_wav(wav)
    fixtures = [wav]
    for suffix in ("flac", "mp3", "ogg"):
        output = fixture_dir / f"tone.{suffix}"
        run_checked(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(wav),
                str(output),
            ]
        )
        fixtures.append(output)

    for audio in fixtures:
        completed = run_checked([str(decoder), str(audio)])
        frames = int(completed.stdout.decode().strip())
        if not 8000 <= frames <= 24000:
            raise AssertionError(f"unexpected frame count for {audio.name}: {frames}")
        print(f"Native decoder smoke: PASS {audio.name} ({frames} frames)")


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("usage: native_worker_ci.py WORKER DECODER FIXTURE_DIR")
    worker = Path(sys.argv[1])
    decoder = Path(sys.argv[2])
    fixture_dir = Path(sys.argv[3])
    if not worker.is_file() or not decoder.is_file():
        raise AssertionError("native test executables are missing")
    protocol_smoke(worker)
    decoder_smoke(decoder, fixture_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
