<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# VerseLatch 1.0.0

VerseLatch is a GTK 4/libadwaita desktop application for creating, verifying,
editing, and saving synchronized LRC timing against local audio.

<img width="850" alt="VerseLatch 1.0.0" src="https://github.com/user-attachments/assets/afc4ef16-f3de-47fc-8748-4d49017ff348">

- **Generate Draft** creates an editable ASR draft when no lyrics file is selected.
- **Verify & Align** keeps existing lyric text authoritative and uses ASR evidence to
  check and correct timing.
- Processing stays on the device. VerseLatch has no telemetry, account system,
  background service, cloud ASR, or lyric-database lookup.

The interface language is US English. Audio and lyrics can be multilingual.

## Requirements

VerseLatch 1.0.0 targets a current Arch Linux x86_64 desktop with GTK 4 and
libadwaita.

Install the runtime packages from the official Arch repositories:

```bash
sudo pacman -S --needed python python-gobject gtk4 libadwaita whisper-cpp aubio util-linux
```

`curl` is needed only if the ASR model is not already installed:

```bash
sudo pacman -S --needed curl
```

Practical baseline:

- 8 GB RAM
- modern 4-core CPU
- SSD recommended
- about 3.2 GiB currently available memory for the ASR safety preflight
- about 2.3 GiB free storage when a model download must be staged and verified

16 GB RAM and 6+ modern CPU cores are recommended for more comfortable full-song
analysis. GPU acceleration is optional and depends on the installed whisper.cpp
backend.

See [System Requirements](docs/SYSTEM_REQUIREMENTS.md) for the complete policy.

## Install

Do not run the installer with `sudo`.

```bash
unzip VerseLatch-1.0.0.zip
cd VerseLatch-1.0.0
./packaging/linux/install-user.sh
```

### First-time model setup

VerseLatch uses the full/non-quantized Whisper Large v3 Turbo model for both
workflows. If a verified copy is not already present, first-time setup downloads
about **1.51 GiB**.

The installer tells you before the download starts, displays curl's real transfer
progress, and verifies the pinned size and SHA-256 before installation. Download
time depends on your connection. A verified model is reused on later installs, so
it is not downloaded again.

Model identity:

- file: `ggml-large-v3-turbo.bin`
- size: `1,624,555,275` bytes
- SHA-256: `1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69`
- source revision: whisper.cpp `98aa99a0a9db05ae2342309f5096248665f7cba3`

The release package does not bundle the model.

## Use

Start VerseLatch from the desktop application menu or run:

```bash
verselatch
```

Typical workflow:

1. Choose an audio file.
2. Optionally enter a short Whisper language code such as `tr`, `en`, `ru`, or `de`;
   the field does not expect full names such as `Turkish` or `English`. Leave it blank
   for automatic detection.
3. Choose an existing `.lrc` or `.txt` file for **Verify & Align**, or leave lyrics
   empty for **Generate Draft**.
4. Run the analysis.
5. Review and edit the LRC preview.
6. Enable **Lyrics and timestamps reviewed**.
7. Choose **Save LRC**.

VerseLatch writes the LRC next to the selected audio. Existing output is backed up
before atomic replacement. If source files change during analysis, VerseLatch
refuses to save against stale input.

### Long analysis

Large v3 Turbo is quality-first and can take several minutes on CPU for a full
song. The application keeps the analysis state visible and provides **Cancel**.
VerseLatch does not invent a percentage when the backend cannot provide a reliable
end-to-end completion estimate.

## Accuracy and review

Whisper is speech recognition, not an authoritative lyrics database. Singing,
heavy effects, overlapping vocals, instrumental sections, and uncommon languages
can produce incorrect or hallucinated text.

Generated text is therefore always an editable draft. Existing lyrics remain the
text authority in Verify & Align. VerseLatch requires explicit human review before
saving.

Alignment uses word-aware ASR timing, bounded lexical matching, monotonic ordering,
and conservative source-to-audio timing models. It does not fill unmatched lyric
lines with equal-gap interpolation.

## Diagnostics

```bash
verselatch --diagnostics
```

Diagnostics remain local unless you choose to share them. Review paths and file
names before posting logs publicly.

## Installed locations

VerseLatch follows the XDG per-user layout:

- application: `$XDG_DATA_HOME/verselatch/app/`
- model: `$XDG_DATA_HOME/verselatch/models/ggml-large-v3-turbo.bin`
- launcher: `~/.local/bin/verselatch`
- state/logs: `$XDG_STATE_HOME/verselatch`
- cache: `$XDG_CACHE_HOME/verselatch`
- desktop ID: `io.github.erhansavas.verselatch`

If `~/.local/bin` is not in your shell `PATH`, the desktop launcher still works.
For Bash, you can add:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Uninstall

```bash
verselatch-uninstall
```

The uninstaller removes VerseLatch-owned application files. It deliberately keeps
user-created LRC files and retains the large model, cache, logs, and configuration
unless you remove those paths yourself.

## Privacy and security

VerseLatch performs runtime audio/lyrics processing locally and does not send
telemetry. Native analysis subprocesses are launched without a shell, under
restricted environment and output-size policies, and are placed in cancellable
process groups.

See:

- [Privacy](docs/PRIVACY.md)
- [Security policy](.github/SECURITY.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Quality policy](docs/QUALITY.md)

## Licensing

VerseLatch first-party application source and artwork are licensed under
**GPL-3.0-only**. The AppStream MetaInfo file is separately licensed under **MIT**.
Per-file SPDX/REUSE metadata is authoritative for file scope.

See [Licensing](docs/LICENSING.md) and
[Third-Party Notices](docs/THIRD_PARTY_NOTICES.txt).

## Versioning

**1.0.0 is the first stable public VerseLatch release.** Public releases use
`MAJOR.MINOR.PATCH` version numbers. The compatibility surface includes documented
CLI behavior, install/uninstall commands, application identity, and LRC workflow
behavior. Patch releases fix compatible defects, minor releases add compatible
functionality, and a major release is reserved for intentionally incompatible
public behavior.

The Python distribution version is kept PEP 440-compatible. Private engineering
candidate labels are not public product versions.

## Project

- Homepage / canonical public repository: `https://github.com/erhansavas/verselatch`
- Issues: `https://github.com/erhansavas/verselatch/issues`
- Application ID: `io.github.erhansavas.verselatch`
- Maintainer identity: `erhansavas`

Project documentation and user-facing interface text are maintained in English.
