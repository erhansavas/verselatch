<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Native worker

Status: **CANDIDATE / BUILD-QUALIFIED on Ubuntu 24.04 x86_64 CI only**. This source tree does not claim runtime ASR or package qualification on any platform yet.

VerseLatch is migrating native audio/ASR work behind one package-owned worker process. The worker is an evidence producer only. It does not align lyrics, rewrite lyric text, render LRC, decide whether Save is allowed, or perform filesystem writes on behalf of the editor. Those product decisions remain in the portable Python domain/application layers.

## Protocol boundary

The worker reads exactly one bounded JSON request from standard input and writes exactly one bounded JSON response to standard output. Protocol version 1 carries a positive request ID, local audio/model references, a language value, and a null lyrics field. Unknown fields, duplicate fields, invalid UTF-8/JSON, unsupported versions, oversized requests, and malformed values are rejected with a typed `INVALID_REQUEST` response when a request ID can be recovered safely.

Successful responses contain bounded ASR segment evidence and a rhythm object. Rhythm analysis is deliberately deferred in the first native slice, so the worker returns an empty rhythm object until that implementation is independently qualified. The portable receiver remains responsible for strict response validation and stale request-ID rejection.

The worker must not expose a generic command-runner API. Runtime networking, shell execution, `system()`, process spawning, model downloading, telemetry, and background-daemon behavior are forbidden.

## Pinned model integrity

VerseLatch accepts only `ggml-large-v3-turbo.bin`, size `1,624,555,275` bytes, SHA-256 `1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69`.

The native worker does not trust a previously verified pathname as sufficient evidence. It opens the model once and passes that same open stream through whisper.cpp's `whisper_model_loader` interface while hashing the bytes actually consumed. Inference starts only after the stream produced exactly the pinned byte count and SHA-256 digest. Path replacement after the worker opens the model therefore cannot substitute different bytes for inference. A first-party SHA-256 implementation performs known-answer self-tests at worker startup; the CI protocol smoke executes that startup path.

This closes the candidate's pathname TOCTOU gap for inference. It is not a claim that arbitrary hostile model files are safe to parse: package/runtime qualification must still keep model acquisition and storage within the verified package-service boundary.

## Pinned build inputs

The candidate build uses immutable upstream revisions:

- whisper.cpp `v1.8.6`, commit `23ee03506a91ac3d3f0071b40e66a430eebdfa1d`, MIT. VerseLatch links the `whisper` library through its stable C interface.
- yyjson `0.12.0`, commit `8b4a38dc994a110abaec8a400615567bd996105f`, MIT. Only `src/yyjson.c` and `src/yyjson.h` are compiled for the worker JSON boundary.
- miniaudio `0.11.24` and stb_vorbis `1.22` are taken from the pinned whisper.cpp source tree. The worker uses only their decoder integration, not whisper.cpp's unrelated example helpers.

The source build may fetch these pinned revisions. Released end-user packages must contain the prebuilt package-owned worker and must not require Git, CMake, a compiler, Python packaging tools, or a separately installed `whisper-cli`.

## Audio path

The intended decoder path is WAV, FLAC, MP3, and OGG/Vorbis to mono 16 kHz 32-bit floating-point PCM, matching the input expected by the whisper C API. This is an implementation target, not a qualified support claim until runtime fixtures exercise all four formats on each package that advertises them.

## Qualification

CI run `31715952895` compiled the worker on Ubuntu 24.04 x86_64 with GCC 13.3 and passed the strict protocol smoke plus the portable/static gates. That evidence makes this worker **BUILD-QUALIFIED only for that CI build environment**. It does not qualify runtime ASR, audio formats, Windows, macOS, ARM64, Android, packaging, cancellation, or release readiness. Those statuses require separate evidence.
