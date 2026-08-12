<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Security Policy

## Threat model

VerseLatch 1.0.0 is a per-user local desktop application. It does not require root privileges and must not be installed with `sudo`.

The main security goals are:

- do not execute paths or lyric text through a shell,
- do not follow attacker-controlled leaf symlinks for app-owned state/output,
- do not silently overwrite changed source/output files,
- do not trust downloaded model bytes without verification,
- do not leave uncontrolled child processes after cancellation/shutdown,
- do not allow faulty native tools to create unbounded output files,
- do not introduce runtime network access.

## Runtime network policy

The application source has no runtime HTTP/socket client dependency. ASR and rhythm analysis call local executables only. There is no telemetry, update checker, cloud lyric lookup, notification service, or background daemon.

The installer may download the missing Whisper model over HTTPS. It uses an immutable upstream revision URL, restricts transfer protocols/redirects to HTTPS, and verifies the exact published byte size and SHA-256 before installation. Runtime rehashes the model once per application process before its first analysis and rejects an in-session identity change.

## Subprocess policy

- no `shell=True`, `os.system`, or `os.popen`,
- whisper/aubio executables are resolved through `/usr/bin:/bin`,
- child environment uses a deterministic executable `PATH` and removes inherited dynamic-loader/Python/shell startup injection variables (`LD_PRELOAD`, `LD_LIBRARY_PATH`, `LD_AUDIT`, `GCONV_PATH`, `PYTHONPATH`, `PYTHONHOME`, `BASH_ENV`, `ENV`),
- each native analysis child is placed in its own process group,
- cancellation and application shutdown terminate the owned process group,
- output is redirected rather than accumulated indefinitely in RAM,
- util-linux `prlimit` gives each child a kernel-enforced maximum regular-file size (32 MiB for Whisper and 2 MiB for each aubio detector), covering diagnostics and generated JSON as they are written.

## Security boundaries

| Input | Trust level | Handling |
|---|---|---|
| Audio file | Untrusted | Bounded regular-file validation; passed as an argv item |
| Lyrics/LRC | Untrusted | Bounded parse; never executed |
| Whisper JSON | Untrusted subprocess output | File-size limited, strictly parsed, bounded before use |
| Whisper model | Untrusted until verified | Pinned revision, exact size, exact SHA-256 |
| Output path | User-controlled | Symlink/identity checks and atomic replacement |

VerseLatch does not claim to sandbox `whisper.cpp` or aubio. Those programs run as the current user and should come from the operating system's trusted package source.

## Input files

Audio and lyric selections are accepted only as bounded regular non-symlink files. Canonical path and file identity are checked so a selection cannot be transparently swapped through a leaf symlink race. Audio and lyrics identity are checked across long analysis; changed input invalidates the result. Delayed worker completions are also gated by a monotonic run ID so an older run cannot mutate a newer UI session.

## Concurrency and stale-result policy

Only one analysis may be active in a window. Each accepted run receives a monotonically increasing identifier. Completion callbacks compare that identifier with the current session before touching widgets or save state. Cancellation uses a typed `AnalysisCancelled` path; an old or cancelled worker result is never converted into a savable result.

The app is not a multi-user security boundary. Same-UID processes can generally interfere with each other on a normal desktop. The file-identity/lost-update checks are designed to fail closed on common accidental or hostile same-user mutations rather than claim immunity from a fully compromised user account.

## Output files

Saving is user initiated. Before replacing an existing LRC, VerseLatch verifies the target state, creates a backup, writes a same-directory temporary file, flushes/fsyncs it, rechecks for a lost update, atomically replaces the target, and fsyncs the directory.

The app does not automatically write merely because analysis completed.

## App-owned directories and logs

State/cache directories are created as private per-user directories. The active log handler uses no-follow semantics for the log leaf. Persistent launcher stderr is bounded and rotated.

## Installer transaction

The installer:

1. verifies the complete package inventory, SHA-256 manifest, and exact source hash,
2. validates packaged shell helpers and host dependencies,
3. verifies, locally copies, or downloads only the exact pinned model,
4. runs model/whisper.cpp/aubio preflights,
5. validates the first-party SVG icon,
6. stages `verselatch.py` and the complete `verselatch_core` package together, then compiles and self-tests that staged payload,
7. performs a static policy/design audit and native GTK populated/empty smoke test,
8. swaps the complete modular app directory as one unit, retaining the previous payload as a rollback snapshot,
9. replaces the launcher, uninstaller, desktop entry, full-color/symbolic icons, and AppStream metadata with per-file rollback backups,
10. removes the old payload snapshot only after the entire owned-file transaction succeeds.

## Reporting

For a local failure, run:

```bash
verselatch --diagnostics
```

Persistent logs are under `$XDG_STATE_HOME/verselatch` (normally `~/.local/state/verselatch`). Remove personal file names before sharing logs publicly if they are sensitive.

## Reporting a vulnerability

Do **not** open a public issue for a suspected security vulnerability. For the public GitHub repository, use **Security → Advisories → Report a vulnerability**. This route depends on GitHub Private Vulnerability Reporting being enabled by the repository owner.

Publication is blocked until the owner has enabled Private Vulnerability Reporting on the actual public repository and verified that repository/security-alert notifications are monitored. If that GitHub feature is ever disabled, this policy must be updated with another real private reporting channel before the release remains supportable. No email address is invented by this project.

## Residual risk

No static or smoke test proves the absence of all bugs. Major residual risks are upstream ASR/native-library bugs, malformed-but-decodable media behavior in system libraries, same-user modification of executable/runtime state, ASR hallucination, and future dependency changes. The release intentionally keeps privileges and network surface minimal to contain those risks.
