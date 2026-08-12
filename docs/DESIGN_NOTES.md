<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# VerseLatch 1.0.0 Design Notes

## Product boundary

VerseLatch is an offline LRC review/alignment tool, not a lyrics search service and not a language-model rewriting system.

The central rule is **evidence before automation**:

- existing lyric words remain authoritative in Verify & Align,
- ASR may support a timing correction but cannot silently replace those words,
- generated text is explicitly called a draft,
- every savable preview requires human review confirmation.

This avoids converting ASR confidence into a false claim that lyrics are correct.


## Interface discipline

The 1.0.0 workbench is intentionally a native utility interface rather than a
marketing/dashboard surface:

- the window title carries the product identity;
- the content heading is task-oriented and compact: **Create LRC**;
- the old workflow explainer card and duplicate privacy footer are removed;
- the header uses a flat `Adw.ToolbarView` treatment so the title bar reads as part of the same calm surface rather than a separate chrome band;
- the primary action uses the native pill shape in open space; disabled actions remain neutral and only the current valid action receives `suggested-action`;
- audio, lyrics, and language share one native libadwaita input surface; status and
  the single primary analysis action sit in open space beneath it; verification and
  preview appear only after analysis;
- confidence evidence is shown as simple key/value rows rather than nested
  metric cards;
- technical details stay collapsed until requested;
- libadwaita provides typography, light/dark colors, focus states, card treatment,
  and semantic action colors; custom CSS is structural only and limited to compact
  layout padding;
- only one enabled suggested action is visually emphasized at a time. Disabled
  actions stay neutral; after review confirmation, **Save LRC** becomes the
  suggested action.
- the primary menu is marked as the GTK primary menu for F10 and exposes a native
  keyboard-shortcuts dialog; Ctrl+O, Ctrl+Shift+O, Ctrl+S, Ctrl+?, and Ctrl+W
  cover the main keyboard workflow.
- a small `GPL-3.0-only · © 2026 erhansavas` caption stays at the bottom of the
  window; detailed licensing remains in **About VerseLatch → Legal**.

The About dialog is the UI source of truth for privacy and licensing. It presents
the application as `GPL-3.0-only` and adds a separate **AppStream Metadata** legal
section under MIT. This keeps the metadata license visible without implying that
the application itself is MIT-licensed.

US English is the interface source language. Copy follows GNOME writing style:
short task-oriented labels, header capitalization for controls/headings, sentence
capitalization for field/body text, and ellipses only when an action requires
further input. Multilingual support applies to audio/lyrics content, not to a
claim that the 1.0.0 UI is localized.

## Appearance

**Follow System** is the default. **Light** and **Dark** are available from the
primary menu for users who need an app-specific preference. All three modes use
libadwaita's native palette and semantic state colors; VerseLatch does not maintain
a separate gray/black palette.

## Model choice

1.0.0 standardizes on the full/non-quantized `large-v3-turbo` whisper.cpp model.

Why this model:

- substantially stronger than the previous Base verifier,
- no Q5 quantization loss in the default quality path,
- much smaller/faster than full Large v3,
- multilingual and suitable for original-language transcription,
- one model keeps caching, diagnostics, installation, and failure behavior simpler.

Full Large v3 was deliberately not made the default. It is roughly twice the model size and substantially more expensive while Turbo is explicitly optimized for much faster transcription with a comparatively small aggregate accuracy tradeoff. VerseLatch chooses a practical quality default rather than a maximum-compute profile.

## whisper.cpp profile

Runtime invokes the system `whisper-cli` directly without a shell.

Important settings:

- full audio (no hidden remote preprocessing),
- `--language <hint>` with `auto` as the default,
- `--max-len 56`,
- `--split-on-word`,
- `--suppress-nst`,
- `--output-json-full`,
- one processor and a bounded CPU thread count,
- no `--no-gpu`; the installed whisper.cpp build may use an available acceleration backend and otherwise runs on CPU.

The cache key binds the audio content/state, model identity, language setting, thread/decode profile, and schema version.

## Word timing

whisper.cpp labels token-level timestamps as experimental. VerseLatch therefore treats token timing as evidence, not ground truth.

When full JSON contains sufficiently complete, finite, monotonic token offsets, VerseLatch maps decoded words to those offsets. If that evidence is absent, it uses a conservative fallback that distributes words only inside an already-short ASR segment. It never extrapolates word timing beyond the segment envelope.

## Word-window matching

A lyric line should not be compared against an entire ASR paragraph when the paragraph contains neighboring lines. 1.0.0 builds one timed ASR word stream and searches contiguous windows close to the expected line length.

To keep the algorithm bounded on long songs, candidate starts come from:

- up to three rare lyric tokens found in the ASR stream,
- a small neighborhood around the source LRC time when available.

Lexical starts receive votes; starts supported by multiple expected tokens rank first. Pathological repetition is capped deterministically. A shared window-text cache avoids rebuilding identical candidate strings.

A bounded beam then selects a monotonic sequence of candidates. Multiple lyric lines can map inside one Whisper segment, but later lines cannot move backward in the ASR word stream.

## Timing model

Source LRC timing is the prior. After text evidence is mapped, VerseLatch prefers the simplest coherent transform:

1. identity,
2. constant offset,
3. small affine drift.

Sparse or contradictory ASR boundaries cannot create arbitrary per-line timestamps. Unmatched lines preserve source timing. Equal-gap interpolation is never used.

## Generation

Generate Draft filters obvious non-lyric stage cues and evaluates repetition/token-probability evidence. A failed automatic quality gate does not delete the draft; it changes the UI to **Draft needs review**. The user may correct a structurally valid preview and explicitly confirm it before saving.

This is intentionally different from automatic lyric correction: VerseLatch cannot know the canonical written lyrics from audio alone.

## Rhythm analysis

`aubiotrack` and `aubioonset` provide local tempo/beat/transient diagnostics. Rhythm evidence does not override textual alignment and is not used to fabricate lyric boundaries.

## Filesystem and lifecycle

- selected inputs must remain regular non-symlink files,
- file identity is rechecked across long analysis,
- subprocesses run in their own process group and are cancellable,
- native output is redirected to temporary files and bounded while it is written by kernel `RLIMIT_FSIZE` limits applied through `prlimit`,
- LRC writes use a backup, fsync, lost-update guard, and atomic replacement,
- state/cache directories are private and leaf symlinks are rejected,
- no daemon or background service is installed.

## Accessibility

Controls use distinct visible labels or explicit accessible names, the language label is associated with its entry, and licensing/warranty information is available from the primary menu. Light, Dark, Follow System, and GNOME High Contrast all delegate functional colors to libadwaita; application CSS contains no hard-coded palette. Release acceptance includes keyboard-only navigation, large text/200% scaling, 1024×600 usable area, high contrast, and Orca.

## Scope decisions intentionally deferred

- source separation (for example Demucs) is not a default dependency; it adds another model/dependency stack and a large new failure surface,
- full Large v3 is not a second bundled profile,
- cloud lyric APIs, LLM rewriting, spell-check services, and automatic web lookup are out of scope,
- GTK-independent parsing, ASR normalization, alignment, storage, native-process and rhythm logic are extracted incrementally behind tests; further UI splitting remains deferred unless characterization tests justify it.


## Architecture rule

VerseLatch does not pursue module count as a quality metric. Pure/testable logic is extracted from the GTK module only when the dependency boundary is clear. The UI remains the orchestration layer; core modules cannot import GTK. A refactor that changes algorithm behavior must be treated as an algorithm change and requalified rather than disguised as cleanup.
