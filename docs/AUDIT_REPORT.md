<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# VerseLatch 1.0.0 Audit Report

> Historical record: this document describes the 1.0.0 pre-publication audit. The 1.0.1 corrective work is tracked by the changelog, release checklist, and current source tests.

Date: 2026-08-12

## Scope

This audit covers the first stable public VerseLatch release: application source,
core alignment/ASR/storage/process logic, GTK/libadwaita integration, installers,
desktop/AppStream metadata, deterministic release tooling, licensing metadata, and
publication gates.

The release is intentionally Linux/Arch-focused and local-first. It does not claim
cross-platform support that has not been implemented and tested.

## Architecture

- Python sources use a setuptools `src/` layout.
- GTK-independent logic lives under `src/verselatch_core` and is exercised by the
  independent pytest suite.
- The GTK module coordinates UI state, worker lifecycle, cancellation, preview, and
  save behavior without using `sys.path` bootstrap mutations.
- Native ASR/rhythm tools are invoked without a shell, with a sanitized environment,
  cancellable process groups, and output-size limits.
- LRC writes use validation, source-state checks, backup behavior, and atomic
  replacement.

## ASR and alignment

VerseLatch uses one pinned full/non-quantized Whisper Large v3 Turbo model for both
Generate Draft and Verify & Align. The model is verified by exact size and SHA-256.

Existing lyric text remains authoritative in Verify & Align. Generated ASR text is
explicitly an editable draft. Alignment uses bounded word-window evidence,
monotonic ordering, and conservative timing models rather than fabricating timing
for unmatched text.

No numerical confidence value is documented as an objective accuracy percentage;
quality evidence remains advisory and user review is mandatory before saving.

## Security and privacy

The release policy checks include:

- no runtime `shell=True`/shell-command execution,
- no runtime network-client imports for analysis,
- no source/test/tool `sys.path` mutation,
- CWD import-shadow resistance for editable and regular installs,
- Bandit medium/high-severity gate,
- Ruff correctness lint,
- secure XML parsing in release verification through `defusedxml`,
- complete SHA-256 package inventory,
- rejection of transient caches, bytecode, symlinks, and special files,
- deterministic archive modes/timestamps,
- installer rollback and post-install GIO registration checks.

Runtime audio, lyrics, file names, diagnostics, and usage data are not transmitted by
VerseLatch. The model installer is the only normal network path and downloads the
pinned model over HTTPS when no verified local copy exists.

## Licensing

- VerseLatch first-party application source and artwork: GPL-3.0-only.
- AppStream MetaInfo: MIT.
- Per-file SPDX/REUSE metadata is authoritative for file scope.
- The release tree is designed to pass REUSE 3.3 validation.
- No song audio, lyric catalog, or scraped lyric database is distributed.

## Desktop integration

The application uses GTK 4/libadwaita, system typography, semantic action styling,
and Follow System/Light/Dark appearance modes. The main workbench is deliberately
compact and uses one input surface instead of dashboard-style cards.

The release gate validates desktop-file/AppStream metadata, the full and symbolic
icons, GTK smoke behavior, the installed launcher, and GLib/GIO application-menu
registration.

## Packaging and reproducibility

The project uses PEP 517/621 metadata and setuptools. Development import behavior is
checked through an editable install; release behavior is checked through a regular
wheel install in an isolated QA copy.

Custom ZIP and tar.gz artifacts are built with normalized modes, timestamps, owner
metadata, path ordering, and compression settings. Independent builds must be
byte-identical. Extracted ZIP/tar contents must match the frozen source tree.

## Versioning

1.0.0 is the first stable public release. VerseLatch uses MAJOR.MINOR.PATCH public
versions. The documented compatibility surface includes CLI behavior,
install/uninstall commands, application identity, and LRC workflow behavior.
Private engineering candidate labels are not public product versions.

## Evidence boundary

Pre-release candidates have repeatedly passed portable and target-Arch gates and
were used to expose and correct packaging, lint, AppStream, GIO, XML-parser, and UI
issues before publication. Those historical candidates are not release artifacts.

The exact final 1.0.0 bytes must still pass the complete native release gate and the
manual real-audio/accessibility acceptance checklist before the `v1.0.0` tag is
published. A prior candidate's PASS is supporting evidence only and is never
substituted for testing the final bytes.
