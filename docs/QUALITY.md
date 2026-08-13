<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Quality and accuracy policy

VerseLatch treats quality as evidence collected at several layers. A green
installer is useful, but it is not a substitute for independent core tests,
metadata validators, real-audio qualification or accessibility testing.

## Accuracy boundary

Whisper is general-purpose speech recognition. Music can mask phonemes, extend
syllables, overlap vocals and encourage repetition. Therefore VerseLatch never
claims that generated words are canonical lyrics.

- **Generate Draft** produces an unverified editable draft.
- **Verify & Align** treats the selected lyric words as authoritative.
- Confidence is diagnostic evidence, not proof of correctness.
- Every save requires a human-reviewed, structurally valid LRC preview.

## Algorithm acceptance metrics

Synthetic and rights-clean fixtures are used to catch deterministic regressions.
Useful metrics include:

- authoritative-text preservation rate: **100%** in Verify & Align fixtures;
- finite/non-negative/strict-monotonic savable timestamps: **100%**;
- deterministic output for identical inputs: **100%**;
- clean affine-drift fixture line-start median absolute error: <= 50 ms;
- clean affine-drift fixture p95 line-start absolute error: <= 100 ms;
- repeated-chorus fixture: correct monotonic occurrence order;
- malformed/non-finite ASR JSON: rejected rather than silently repaired into
  trusted timing evidence;
- hallucination/stage-cue fixtures: never silently saved as authoritative text.

These synthetic thresholds are regression alarms, not claims about arbitrary
real songs. Real-world quality is separately tested on private audio for which
the tester has permission to use it.

## Test layers

### 1. Pure/core tests

`pytest` covers LRC parsing/rendering, Unicode/Turkish matching normalization,
Whisper JSON normalization, draft assessment, alignment/timing fitting,
filesystem writes, process-environment policy, rhythm diagnostics and release
tooling. Deterministic randomized round trips provide lightweight property-like
coverage without making a third-party property framework a runtime dependency.

Hypothesis is useful as an optional development tool for parser/round-trip
fuzzing, but is not required by the application or release artifact.

### 2. Policy/static tests

`tools/verify_tree.py` independently audits release-tree shape, runtime network
imports, `shell=True`, native Popen policy, model identity consistency,
SPDX/license family, private AppStream truthfulness, original SVG provenance,
forbidden bundled asset types, release-mode policy and the explicit Save-only
LRC writer boundary.

### 3. Tooling/metadata tests

On the target Arch QA host:

- Ruff: high-signal syntax/import/undefined-name correctness rules (`E4`, `E7`, `E9`, `F`);
- ShellCheck: installer/model helper/uninstaller/quality scripts;
- REUSE lint: file-level licensing/provenance structure;
- `desktop-file-validate`: desktop integration;
- `appstreamcli validate --pedantic`: AppStream syntax/policy;
- Bandit: required fail-closed scan for medium/high-severity findings across
  shipped Python source and release tools; findings must be fixed or narrowly
  reviewed before the native gate can pass.

A full mypy/pyright gate is deliberately deferred. The GTK/PyGObject-heavy UI
is not yet annotated deeply enough for a strict type checker to provide a good
signal-to-maintenance ratio. New pure core APIs should continue gaining type
hints so this can be revisited incrementally.

### 4. Integration/native tests

`tools/native_release_check.sh` validates the exact extracted candidate on the
real Arch stack: syntax, static policy, independent tests, metadata, ShellCheck,
REUSE, built-in self-test, GTK smoke, model identity, transactional personal
installation, and GLib/GIO desktop-menu discoverability after installation.
Installed application launches use `-E -s -B`: Python environment overrides are
ignored, the user site is excluded, and bytecode writes are disabled while the
installer-owned application directory remains the normal import root for the
adjacent `verselatch_core` package. Build/import-boundary probes use `-I` where
they intentionally test installed-package isolation. Package and staged-install
inventories are rechecked after runtime tests so validation cannot silently mutate
the frozen payload.

The release candidate uses the strict public AppStream profile with the canonical GitHub homepage and issue tracker. Public validation must complete with zero diagnostics, and `tools/public_release_check.sh` independently checks the exact metadata and HTTPS endpoints before tagging. The same frozen bytes must then pass the full native and manual acceptance gates.

### 5. Manual real-world acceptance

Before any public release, the exact frozen candidate must additionally pass:

- Generate Draft on representative permitted audio;
- Verify & Align against a known LRC/lyrics regression case;
- Turkish/non-ASCII content;
- cancel during Whisper and during retry/recovery paths;
- save, re-save, backup and read-only/disk-error behavior where practical;
- keyboard-only workflow;
- GNOME large text and 200% scaling;
- 1024x600 usable area;
- high-contrast mode;
- Orca screen-reader smoke;
- on-screen keyboard where available.


## Interface quality gate

UI quality is treated as an invariant rather than subjective polish. Static and
native checks protect the following rules:

- About is the single UI source of truth for the runtime privacy statement;
- the application license is `GPL-3.0-only`, while AppStream metadata is exposed
  as a separate MIT legal section;
- no legacy marketing/workflow slogan or duplicate privacy footer may return;
- appearance choices live in the primary menu as Follow System, Light, and Dark,
  with Follow System as the default;
- custom CSS is structural only and must not hard-code fonts, palette colors, or
  replace libadwaita semantic states;
- a ready-to-save preview makes Save LRC the sole suggested action;
- technical details are collapsed by default and review confirmation is explicit;
- manual acceptance still covers narrow/large-text layouts, keyboard navigation,
  high contrast, and Orca because automated smoke tests cannot prove usability.

## Performance/resource policy

Large v3 Turbo is compute-intensive and intentionally used as the single 1.0.1 ASR model. VerseLatch checks
available memory before analysis, bounds CPU threads, leaves acceleration
backend choice to the installed whisper.cpp build, limits native output files,
and keeps the GTK main loop free of long ASR work.

Long-running operations communicate activity without fake precision: analysis exposes an inline spinner, current status, and Cancel; first-time model download exposes curl transfer progress. Time estimates are not fabricated when the application cannot calculate them reliably.

The memory preflight is a safety floor, not a promise that every hardware/backend
combination will succeed. Long files remain bounded by source/output limits and
analysis is cancellable. The project should prefer predictable failure with a
clear message over swapping the desktop into an unusable state.

## No metric theater

Coverage percentage, lint count and synthetic timing scores are tools, not the
product goal. A line is not made safe by being covered; an ignored warning is
not made correct by making a dashboard green. Release decisions are based on
the invariants in `INVARIANTS.md` and the acceptance matrix in
`RELEASE_CHECKLIST.md`.
