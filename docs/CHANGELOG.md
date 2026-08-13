<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Changelog

## 1.0.1 — 2026-08-13

- Reject saving Verify & Align results when the analyzed lyrics source changed, disappeared, was replaced, or no longer matches the current selection.
- Add fail-closed ownership manifests for per-user install, reinstall, upgrade, and uninstall paths, including exact recognition of an unmodified 1.0.0 installation.
- Add minimal portable GitHub Actions checks while retaining Arch/native qualification as a separate release gate.
- Clarify that launcher stderr rotation occurs between launches rather than imposing a hard bound during one process lifetime.
- Replace the historical MIT license-text placeholder with the actual first-party copyright notice.

## 1.0.0 — 2026-08-12

First stable public release.

### LRC workflow

- Generate editable LRC drafts from local audio with Whisper Large v3 Turbo.
- Verify and align existing `.lrc` or `.txt` lyrics while preserving selected lyric text.
- Review and edit generated timing/text before saving.
- Require explicit review confirmation before **Save LRC** becomes available.
- Back up existing output and replace it atomically.
- Reject stale or changed source files rather than saving against mismatched input.

### Alignment and ASR

- Use word-aware Whisper segmentation and token timing when available.
- Use bounded contiguous word-window matching, monotonic ordering, and conservative
  source-to-audio timing models.
- Preserve unmatched lines instead of fabricating equal-gap timing.
- Support short Whisper language codes such as `tr`, `en`, and `ru`, with blank input
  selecting automatic language detection.
- Pin the full/non-quantized Large v3 Turbo model by immutable upstream revision,
  exact size, and SHA-256.

### Desktop experience

- GTK 4/libadwaita interface with Follow System, Light, and Dark appearance choices.
- Compact task-oriented workbench with one primary action and adaptive scrolling.
- Keyboard shortcuts, visible cancellation, local status feedback, and review-before-save
  interaction.
- About, privacy, project links, and file-scoped legal information integrated with
  libadwaita patterns.

### Packaging and security

- PEP 517/621 setuptools project with a `src/` layout and PEP 660 editable-development
  validation.
- Per-user XDG installation with transactional replacement and rollback safeguards.
- Deterministic ZIP and tar.gz release tooling with normalized timestamps/modes.
- Complete internal SHA-256 package inventory.
- Ruff, pytest, Bandit, ShellCheck, REUSE 3.3, desktop/AppStream validation, import
  boundary tests, CWD-shadow resistance, and native GTK/GIO release gates.
- Native subprocesses execute without a shell and use sanitized environments,
  cancellable process groups, and bounded output files.
- XML verification tooling uses `defusedxml`.

### Privacy and licensing

- Runtime analysis is local; no telemetry, cloud ASR, account service, lyric lookup,
  background service, advertising, or automatic update check is included.
- Application source/artwork: GPL-3.0-only.
- AppStream MetaInfo: MIT.
- SPDX/REUSE metadata and third-party notices are included in the release source.
