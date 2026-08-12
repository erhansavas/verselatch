<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# VerseLatch invariants

These rules are release requirements, not aspirations. A code change that
breaks one invalidates the release candidate.

## Content and timing

1. **Verify & Align preserves lyric words.** Matching normalization is internal
   evidence only; user/source text is not silently rewritten.
2. **Generate Draft is never presented as authoritative lyrics.** It remains
   editable and requires explicit human review before Save.
3. **Savable LRC timestamps are finite, non-negative and strictly increasing.**
4. **Unknown timing is not fabricated by equal-gap interpolation.**
5. **Aubio beat/onset evidence never overrides textual/vocal alignment.**
6. **Alignment is deterministic for identical validated inputs.**

## Source and lifecycle

7. **Selected audio and lyric source files are read-only inputs.** Analysis and
   Save never modify them in place.
8. **Source mutation invalidates the run.** If audio or lyrics change during a
   long analysis, the result is discarded.
9. **Cancellation writes no LRC.** A cancellation is a typed lifecycle result,
   not a generic successful completion.
10. **A stale worker result cannot update a newer session.** `analysis_run_id`
    gates delayed GLib callbacks.
11. **Only the explicit Save action writes an LRC during normal runtime.**
12. **A failed save never truncates a previously good LRC.** Existing output is
    backed up and replacement is same-directory, fsynced and atomic.

## Native processes and privacy

13. **Normal runtime is network-free.** Model acquisition is a separate,
    explicit helper.
14. **External native tools are invoked by argv, never through a shell.**
15. **Native children receive an explicit sanitized environment and a new
    process group.** Dangerous loader/Python/shell startup variables are not
    inherited and cannot be reintroduced through internal overrides.
16. **Native stdout/stderr is bounded or redirected to bounded temporary
    files.** Large child output is not accumulated unbounded in Python memory.
17. **No root privilege, telemetry, account, daemon or hidden background
    service is part of the application runtime.**

## Model and filesystem

18. **The Whisper model is unusable until its exact expected identity is
    satisfied:** pinned revision, exact `1,624,555,275` bytes and SHA-256
    `1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69`.
19. **Trusted input/model leaf paths must be regular files, not symlinks or
    special files.**
20. **Package archives contain no model weights, audio, custom fonts or native
    third-party binaries.**
21. **Installer replacement is whole-payload transactional.** `src/verselatch.py`
    and `src/verselatch_core` are staged and tested together, then the app payload
    directory is swapped as one unit; later installer failure restores the
    previous payload.
22. **Uninstaller ownership is narrow.** It removes VerseLatch-owned installed
    program/metadata paths and does not delete user-created LRC files.

## Release integrity

23. **Every regular release file except `SHA256SUMS` is listed by the manifest.**
24. **Archive executable modes are source-controlled, not inherited from the
    build workstation.**
25. **Two clean builds of one frozen source state must be byte-identical.**
26. **Any byte change after native validation creates a new candidate, hash and
    full affected-gate rerun.**
27. **Public AppStream metadata is truthful and canonical.** The final release candidate uses the reachable GitHub homepage and issue tracker in AppStream and PEP 621 metadata, carries no development release marker, and must pass strict public validation with zero diagnostics.
28. **The native Python security scan is fail-closed.** Bandit is required and
    medium/high-severity findings cannot be skipped to obtain a green gate.
29. **Test discovery is isolated from ambient pytest plugins.** Release tests use
    importlib mode, strict configuration, and plugin-autoload disabling.
30. **The application does not own a parallel color palette.** Follow System is
    the default; Light and Dark delegate palette and semantic states to libadwaita.
31. **The internal Python wheel is a QA artifact, not the public installation channel.** Public distribution is the GitHub source/application release; release documentation does not instruct users to upload or install the wheel from PyPI.
32. **US English is the interface source language for 1.0.0.** Multilingual
    audio/lyrics support does not imply an unimplemented UI localization.
