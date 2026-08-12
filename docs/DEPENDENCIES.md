<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Dependency and Supply-Chain Inventory

Date reviewed: 2026-08-12

## Shipped in this source ZIP

The archive contains VerseLatch source, installer/uninstaller/model-install scripts, first-party Linux desktop/AppStream metadata plus original full-color and symbolic VerseLatch SVG icons, GitHub contribution templates, checksums, and project documentation. It contains no third-party source tree, Python wheel, native executable, model, audio, lyric corpus, font, or JavaScript package.

The source distribution includes the standard unmodified GNU GPL version 3 text and does not require a runtime license-data package.

## Runtime components supplied by the operating system

| Component | Purpose | Upstream/project license | Bundled? |
|---|---|---|---|
| Python | Runs the installed VerseLatch Python payload | PSF-2.0 | No |
| PyGObject | Python GObject/GTK bindings | LGPL-2.1-or-later | No |
| GTK 4 | Desktop toolkit | LGPL-2.1-or-later | No |
| libadwaita | GNOME application widgets | LGPL-2.1-or-later | No |
| whisper.cpp / `whisper-cli` | Local ASR | MIT | No |
| aubio CLI | Local rhythm diagnostics | GPL-3.0-or-later | No |
| util-linux `prlimit` | Kernel-enforced child file-size limits | GPL-2.0-or-later for `prlimit` | No |

These are ordinary separate system components. VerseLatch invokes the three CLI families without a shell and loads the platform GUI/Python libraries normally. The native command-line tools and GUI libraries are separately installed dependencies rather than vendored project source. Their own licenses remain in force; compatibility and notices are reviewed before distribution.

## Installer-only components

The installer uses normal Arch/base userland tools including Bash, coreutils (`sha256sum`, `timeout`, `install`, and related commands), util-linux, and optionally `curl`. These tools are not copied into the VerseLatch installation. `curl` is used only when the pinned model is absent or invalid.

## Whisper model

| Field | Value |
|---|---|
| File | `ggml-large-v3-turbo.bin` |
| Source repository | `ggerganov/whisper.cpp` on Hugging Face |
| Pinned revision | `98aa99a0a9db05ae2342309f5096248665f7cba3` |
| Size | 1,624,555,275 bytes |
| SHA-256 | `1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69` |
| Upstream license | MIT |
| Bundled in ZIP | No |

The installer uses an immutable revision URL, HTTPS-only redirects, an expected maximum transfer size, the exact byte size, and the exact SHA-256. Runtime hashes the model once per application process before its first analysis and rejects changes or mismatches.

## Supported Arch baseline observed on the review date

The supported target is current Arch Linux x86_64, not a frozen private dependency bundle. On 2026-08-12 the official repositories exposed Python 3.14.6-1, PyGObject 3.56.3-1, GTK 1:4.22.4-1, libadwaita 1:1.9.2-1, whisper-cpp 1.9.1-1, and aubio 0.4.9-24. The installer checks required APIs/CLI flags and native behavior rather than trusting version strings alone.

Future package updates can change behavior. A public release must be tested from the exact ZIP on the then-current supported Arch system, and security advisories for all native dependencies must be reviewed again at release time.

### Maintainer XML validation dependency

Release-tree AppStream/SVG structural validation uses `defusedxml` rather than the Python stdlib XML parser. On Arch, install the official `python-defusedxml` package. This is a maintainer/release-QA dependency; it is not part of the VerseLatch runtime payload.
