<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Contributing to VerseLatch

VerseLatch is deliberately small, local, and fail-closed. Contributions should preserve that boundary.

## Before opening a change

- Use the public GitHub issue tracker for ordinary bugs and feature proposals.
- Do **not** publish suspected security vulnerabilities in an issue. Follow [the security policy](../.github/SECURITY.md) instead.
- Keep runtime behavior offline: no telemetry, cloud APIs, update checkers, accounts, notifications, background services, or automatic lyric lookup.
- Do not add generated model files, user audio, lyrics, caches, logs, or Python bytecode to the repository.
- Keep user-visible text, project prose, logs, and code comments in English.
- Preserve explicit preview/review before any LRC save.

## Validation

For source changes, run the packaged self-test and the policy checks used by `packaging/linux/install-user.sh`. On Arch Linux, also exercise the native GTK/whisper.cpp/aubio preflight and relevant manual workflow before proposing a release.

Small, behavior-preserving changes are preferred over speculative rewrites. Security or data-integrity changes should explain the threat or failure mode they address.

## Contribution licensing and provenance

By submitting a contribution, you represent that you have the right to submit
that material and agree that the contribution may be distributed as part of
VerseLatch under `GPL-3.0-only`, unless a different compatible license is
explicitly documented for that file. Contributors retain copyright in their
own contributions.

Do not submit copied code, generated assets derived from third-party branding,
lyrics, audio, fonts, icons, datasets, or other material when its origin or
license is unclear. Record any permitted third-party material in the relevant
SPDX/REUSE metadata and `THIRD_PARTY_NOTICES.txt` before it is merged.

## Versioning

Public VerseLatch releases use `MAJOR.MINOR.PATCH` version numbers. `1.0.0` is the
first stable public release. The documented compatibility surface includes CLI
behavior, install/uninstall commands, application identity, and LRC workflow
behavior. Patch releases are compatible fixes, minor releases add compatible
functionality, and major releases are reserved for intentionally incompatible
public behavior.

Python package versions remain PEP 440-compatible. Private engineering candidate
labels are not published as product versions.
