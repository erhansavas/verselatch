<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Native worker

Status: **CANDIDATE**. This source tree does not claim runtime qualification on any platform yet.

VerseLatch is migrating native audio/ASR work behind one package-owned worker process. The worker is an evidence producer only. It does not align lyrics, rewrite lyric text, render LRC, decide whether Save is allowed, or perform filesystem writes on behalf of the editor. Those product decisions remain in the portable Python domain/application layers.

## Protocol boundary

The worker reads exactly one bounded JSON request from standard input and writes exactly one bounded JSON response to standard output. Protocol version 1 carries a positive request ID, local audio/model references, a language value, and a null lyrics field. Unknown fields, duplicate fields, invalid UTF-8/JSON, unsupported versions, oversized requests, and malformed values are rejected with a typed `INVALID_REQUEST` response when a request ID can be recovered safely.

Successful responses contain bounded ASR segment evidence and a rhythm object. Rhythm analysis is deliberately deferred in the first native slice, so the worker returns an empty rhythm object until that implementation is independently qualified. The portable receiver remains responsible for strict response validation and stale request-ID rejection.

The worker must not expose a generic command-runner API. Runtime networking, shell execution, `system()`, process spawning, model downloading, telemetry, and background-daemon behavior are forbidden.

## Pinned build inputs

The candidate build uses immutable upstream revisions:

- whisper.cpp `v1.8.6`, commit `23ee03506a91ac3d3f0071b40e66a430eebdfa1d`, MIT. VerseLatch links the `whisper` library through its stable C interface.
- yyjson `0.12.0`, commit `8b4a38dc994a110abaec8a400615567bd996105f`, MIT. Only `src/yyjson.c` and `src/yyjson.h` are compiled for the worker JSON boundary.
- miniaudio `0.11.24` and stb_vorbis `1.22` are taken from the pinned whisper.cpp source tree. The worker uses only their decoder integration, not whisper.cpp's unrelated example helpers.

The source build may fetch these pinned revisions. Released end-user packages must contain the prebuilt package-owned worker and must not require Git, CMake, a compiler, Python packaging tools, or a separately installed `whisper-cli`.

## Audio path

The intended decoder path is WAV, FLAC, MP3, and OGG/Vorbis to mono 16 kHz 32-bit floating-point PCM, matching the input expected by the whisper C API. This is an implementation target, not a qualified support claim until runtime fixtures exercise all four formats on each package that advertises them.

## Qualification

The first CI target is Ubuntu x86_64 compile + protocol smoke testing. A successful compile makes this worker at most **BUILD-QUALIFIED** for that build environment; it does not qualify runtime ASR, audio formats, Windows, macOS, ARM64, Android, packaging, cancellation, or release readiness. Those statuses require separate evidence.
