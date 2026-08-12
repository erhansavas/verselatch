<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# VerseLatch architecture

VerseLatch is a local lyrics timing workbench. Its job is deliberately
narrow: turn local audio plus optional lyrics/LRC into a reviewable timing
draft, then write an LRC only after an explicit human review and save action.

## Product data flow

```text
Audio file
    |
    +--> whisper-cli --> validated word/segment evidence --+
    |                                                       |
    +--> aubio --------> rhythm diagnostics ----------------+--> alignment
                                                            |
Existing lyrics/LRC ----------------------------------------+
                                                            v
                                                     review/editor
                                                            |
                                                            v
                                                   atomic .lrc save
```

Aubio evidence is diagnostic. VerseLatch does **not** snap lyric boundaries to
beats or onsets: a beat is not proof that a vocal line starts there.

## Package boundaries

```text
src/verselatch.py
    GTK/libadwaita application, session controller, adapters, diagnostics
        |
        +--> verselatch_core.lrc
        |       lyric parsing, matching normalization, LRC rendering
        +--> verselatch_core.asr
        |       untrusted whisper JSON normalization and draft assessment
        +--> verselatch_core.alignment
        |       word-window evidence, monotonic mapping, robust timing model
        +--> verselatch_core.storage
        |       regular-file reads, identity checks, atomic LRC writes
        +--> verselatch_core.process
        |       native environment policy and process-group termination
        +--> verselatch_core.rhythm
        |       bounded aubio parsing and diagnostic summaries
        +--> verselatch_core.constants / errors
```

Dependency direction is one-way: core modules do not import GTK. The UI may
call the core; the core must not know about widgets, colors, dialogs, or the
GLib main loop. This makes algorithm and filesystem behavior testable without
a desktop session.

The main GTK module is still intentionally conservative rather than being
rewritten wholesale. Pure logic is extracted first; UI decomposition can
continue later only behind characterization tests.

## Workflow state model

The user-facing mental model is:

```text
No source
   |
   v
Source selected ----> analyzing ----> reviewable draft ----> saving ----> saved
   ^                      |                    |                 |
   |                      +--> cancelled -----+                 +--> error
   |                      +--> failed --------+                         |
   +----------------------------------------------------------- retry --+
```

There are two analysis modes:

- **Generate Draft**: audio is authoritative evidence; ASR text is explicitly
  unverified and editable.
- **Verify & Align**: selected lyric text is authoritative. ASR can support a
  timing proposal but must not silently rewrite the lyric words.

Invalid transitions are rejected in the UI: analysis cannot start without an
audio source, a second analysis cannot start while one is active, and Save is
not enabled until a structurally valid preview has been explicitly reviewed.

Each analysis receives a monotonically increasing `analysis_run_id`. A delayed
GLib callback from an older worker is discarded if its run identifier is no
longer current. Audio and lyrics file identity are checked across the long
analysis operation; a changed source invalidates the result rather than mixing
old and new evidence.

## Alignment design

VerseLatch deliberately uses a bounded, deterministic sequence-alignment
pipeline rather than unrestricted per-line retiming:

1. Normalize text for *matching only* using Unicode NFKC/casefold/NFKD,
   combining-mark removal, Turkish dotless-I folding, and punctuation-aware
   tokenization. Displayed/user lyric text is not normalized or rewritten.
2. Prefer native whisper token timing when sufficiently usable; otherwise use
   conservative timing inside an already-short segment envelope.
3. Generate a small set of candidate contiguous ASR word windows using rare
   lyric tokens and, when available, a broad source-time prior.
4. Select a monotonic path with a bounded beam. Repeated choruses cannot move
   backward in the ASR stream; deterministic tie-breaking prevents run-to-run
   drift.
5. For existing LRC timing, prefer the simplest coherent correction: identity,
   then constant offset, then a bounded affine drift model only when broad
   evidence materially improves robust residual error.
6. Unmatched lines keep trustworthy source timing. VerseLatch does not fill
   unknown timing with equal-gap interpolation.

The candidate count, beam width, lyric-line count, ASR-segment count and parsed
output sizes are bounded. This keeps pathological repetition from turning the
small desktop tool into an unbounded dynamic-programming workload.

## Trust boundaries

| Input/dependency | Trust status | Handling |
|---|---|---|
| Audio | Untrusted | regular non-symlink validation, size bound, identity re-check |
| Lyrics/LRC | Untrusted | bounded UTF-8 read, strict timestamp parser, identity re-check |
| whisper JSON | Untrusted child output | kernel file-size bound, strict parse, finite/bounded timing validation |
| Whisper model | Untrusted until verified | exact filename, byte length and SHA-256 |
| whisper.cpp / aubio | OS dependency | fixed system executable path, argv invocation, sanitized inherited environment, current-user privileges |
| Output path | User-controlled filesystem | regular-file/symlink checks, backup, same-directory temporary file, fsync, atomic replace |
| Worker completion | Untrusted if stale | run-id comparison before UI mutation |

VerseLatch does **not** claim to sandbox whisper.cpp or aubio. They execute as
the current user. The security model limits and supervises them; it does not
pretend that process groups or resource limits are a sandbox.

## Runtime/network boundary

Normal analysis contains no networking client and does not download anything.
The separate `packaging/linux/install-model.sh` helper is the sole intentional
network path: when no verified local/legacy model exists, it downloads one
pinned HTTPS object and accepts it only after exact byte-size and SHA-256
verification.

## Persistence boundary

VerseLatch owns its application payload, launcher, desktop metadata, icons and
its XDG state/cache/config/model locations. Uninstalling the application does
not delete user LRC files and deliberately preserves model/cache/state/config
unless the user removes them separately.
