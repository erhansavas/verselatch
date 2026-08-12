<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# System Requirements

## Supported release target

VerseLatch 1.0.0 targets a current **Arch Linux x86_64** desktop with GTK 4/libadwaita and the official Arch `whisper-cpp` and `aubio` packages.

The code is intentionally ordinary Python/PyGObject and may be portable later, but Windows, Android, Flatpak, and other distributions are not claimed as supported by this release.

## Software floor

- Python 3.10+
- GTK 4.16+
- libadwaita 1.8+
- PyGObject
- whisper.cpp CLI with `--output-json-full`, `--max-len`, `--split-on-word`, `--language`, and `--suppress-nst`
- aubio CLI (`aubiotrack`, `aubioonset`)
- util-linux `prlimit`

As of 2026-08-12, Arch stable provides a newer stack than these minimums, including Python 3.14.6-1, whisper-cpp 1.9.1-1, PyGObject 3.56.3-1, GTK 1:4.22.4-1, libadwaita 1:1.9.2-1, and aubio 0.4.9-24.

## Release/maintainer QA tools

The frozen native release gate additionally requires the Arch packages that provide pip/setuptools and the QA stack, including Ruff, Bandit, ShellCheck, REUSE, desktop-file-utils, and AppStream. These are maintainer/test dependencies, not application runtime dependencies. PEP 621/PEP 660 boundary checks need `python-pip` and `python-setuptools`; the fail-closed Python security scan requires the official Arch `bandit` package, and the release-tree XML validation uses the official `python-defusedxml` package so XML safety checks do not rely on the stdlib parser for potentially hostile content.

## Hardware policy

The Large v3 Turbo model requires substantial memory and compute; the following baselines define the supported 1.0.0 target.

### Practical baseline

- 64-bit x86 CPU
- 4 modern CPU cores
- 8 GB system RAM
- SSD strongly preferred
- at least 3.2 GiB currently available memory before analysis

This level is suitable for testing and normal use if the user accepts slower full-song ASR.

### Comfortable recommendation

- 6+ modern CPU cores
- 16 GB RAM
- SSD/NVMe storage
- optional GPU/accelerator backend supported by the installed whisper.cpp build

VerseLatch does not pass `--no-gpu`. If whisper.cpp exposes a compatible acceleration backend, its normal backend selection may use it; otherwise CPU inference remains supported.

## Model/storage

The default model is `ggml-large-v3-turbo.bin`:

- exact size: 1,624,555,275 bytes (~1.51 GiB),
- installer staging requirement: about 2.3 GiB free when the model is missing,
- the model is stored once in `$XDG_DATA_HOME/verselatch/models`,
- first-time download is ~1.51 GiB; the installer shows transfer progress and reuses a verified local model on later installs.

The 3.2 GiB `MemAvailable` gate is a VerseLatch operational safety margin, not an upstream statement that every system requires exactly that amount.

## Thread policy

VerseLatch chooses a bounded thread count from logical CPU count and caps it at 8. On an 8-thread CPU it uses 4 ASR threads. The goal is to avoid saturating every logical CPU and keep the desktop usable while analysis runs.

The process is also started with a lower Unix scheduling priority when `nice` is available. This does not reduce output quality; on an otherwise idle machine it normally still receives available CPU time.
