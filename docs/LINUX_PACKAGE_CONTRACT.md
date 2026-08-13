<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Linux 1.1 Package Contract

This document defines the Linux application-payload contract for the VerseLatch
1.1 development line. It does not change or reinterpret the immutable 1.0.1
release, tag, assets, or historical installation manifest.

## Per-user payload

The transactional per-user application directory is:

`$XDG_DATA_HOME/verselatch/app`

with the default XDG fallback of `$HOME/.local/share/verselatch/app`.

A complete 1.1 application payload owns these entries together:

- `verselatch.py`
- `verselatch_core/`
- `verselatch_app/`
- `verselatch_platform/`
- `bin/verselatch-worker`

The application directory is one replacement unit. Python code and the native
worker must not be upgraded independently inside that unit.

## Native worker

`bin/verselatch-worker` is package-owned. End users must not need `whisper-cli`,
a compiler, CMake, Ninja, Git, pip, or PATH edits to obtain or run the worker.

The Git source tree intentionally does not contain a prebuilt worker binary.
Maintainer-side packaging must build the pinned native worker, qualify it, and
inject that exact executable into the binary application payload before the
payload can be offered to users.

The installed worker must be an executable regular file and must not be a
symbolic link. Runtime code receives its absolute path explicitly through the
platform composition root; application/domain code does not search PATH.

## Model

The verified `ggml-large-v3-turbo.bin` model remains outside the transactional
application payload under the VerseLatch XDG data model directory. Reinstalling
or uninstalling the application does not silently delete the model.

The model identity remains fixed by exact filename, byte size, and SHA-256.

## Architecture scope

A binary payload is architecture-specific. Linux package qualification currently
recognizes `x86_64`/`amd64` and `aarch64`/`arm64` as architecture families.
A successful build on one architecture does not qualify the other.

## Ownership and uninstall

The 1.1 ownership manifest must cover the complete application tree including
`bin/verselatch-worker`, plus the launcher and other fixed managed files.
Unknown collisions remain fail-closed.

A valid historical 1.0.1 ownership manifest remains an upgrade input; it is not
rewritten in place or treated as a 1.1 manifest. Models, cache, logs, config, and
user-created LRC files remain outside the managed application tree.

## Maintainer worker bundle

Before installer/package migration, the maintainer-side native build is staged as
an intermediate architecture-specific worker bundle outside the Git source tree.
The bundle has exactly these regular-file members:

- `app/bin/verselatch-worker`
- `metadata/worker-provenance.json`
- `SHA256SUMS`

The provenance record binds the worker byte size and SHA-256 to the canonical
Linux architecture, the source-tree `SHA256SUMS` identity, the exact source
commit supplied by the build environment, and the pinned whisper.cpp and yyjson
commits. The staging verifier rejects symlinks, unexpected inventory, manifest
or provenance mismatch, architecture mismatch, and worker tampering.

This intermediate worker bundle is maintainer evidence/staging input, not a
standalone end-user application package and not a reason to commit a prebuilt
worker binary to the source tree.

## Release rule

A source archive is not by itself an end-user Linux binary package. Any release
that claims normal-user Linux runtime support must provide a qualified prebuilt
worker through an architecture-specific package/bundle and must pass installed
payload verification without relying on system `whisper-cli` or `aubio`.
