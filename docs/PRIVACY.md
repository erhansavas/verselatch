<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Privacy

Processing runs on this device. VerseLatch does not send telemetry or run a background service.

## Runtime

VerseLatch 1.0.1 does not send audio, lyrics, generated text, file names, diagnostics, or usage data to a server. It contains no telemetry, analytics, advertising, cloud ASR, cloud lyric lookup, account system, or automatic update check.

Whisper and aubio analysis run through local system executables. ASR cache and diagnostic logs stay in the user's XDG directories.

## Installation

If the verified Large v3 Turbo model is missing, the installer downloads that model once over HTTPS from an immutable revision in the official `ggerganov/whisper.cpp` Hugging Face repository and verifies its exact size and SHA-256. Reinstallation can remain offline when the valid model is already present; `curl` is then not required. Runtime performs no update or model network check.

System packages are installed only when the user explicitly runs the shown `pacman` command. The VerseLatch installer itself never invokes `sudo`.

## Local data

- LRC output is written next to the selected audio only after explicit review/save.
- Logs may contain local file names and technical analysis status because they are meant for debugging; lyric bodies are not intentionally written to the normal application log.
- Cache entries can contain locally generated ASR text, timing, and confidence evidence. They are content-bound and remain only in the local VerseLatch cache.
- The uninstaller keeps model/cache/log/config data unless the user removes those paths manually. This conservative default avoids destructive cleanup, but users handling sensitive material should inspect and delete retained cache/log data when appropriate.
