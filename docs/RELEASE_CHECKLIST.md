<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# VerseLatch 1.0.0 Release Checklist

Use this checklist on the exact frozen release bytes.

## Automated release gate

- [ ] `sha256sum` matches the published candidate hash.
- [ ] `./tools/public_release_check.sh` prints `PUBLIC RELEASE CHECK: PASS`.
- [ ] `./tools/native_release_check.sh` prints `NATIVE RELEASE CHECK: PASS`.
- [ ] pytest, editable/regular import-boundary tests, wheel inventory, Ruff, Bandit,
      ShellCheck, REUSE, desktop/AppStream validation, GTK smoke, model verification,
      installer transaction, and GIO registration all pass inside the native gate.
- [ ] `verselatch --version` prints `VerseLatch 1.0.0`.
- [ ] `verselatch --diagnostics` exits successfully.

## Functional acceptance

- [ ] Generate Draft is tested with real audio.
- [ ] Verify & Align is tested with an existing LRC/TXT source.
- [ ] A known non-English track is tested with an explicit short language code.
- [ ] Turkish/non-ASCII characters survive preview, save, reopen, and re-save.
- [ ] Cancel stops active analysis, writes no LRC, and a new analysis can start.
- [ ] Editing the preview clears review confirmation.
- [ ] Save remains unavailable until **Lyrics and timestamps reviewed** is enabled.
- [ ] Existing output backup and atomic replacement are exercised.
- [ ] A changed source file is rejected rather than saved against stale input.

## Installation acceptance

- [ ] Missing-model setup clearly announces the ~1.51 GiB download.
- [ ] Actual transfer progress is visible during model download.
- [ ] The downloaded model passes size/SHA-256 verification.
- [ ] Reinstall reuses a verified model without downloading it again.
- [ ] Desktop application entry and icon appear after installation.
- [ ] Uninstall preserves user LRC files and retained data exactly as documented.

## UI and accessibility

- [ ] Follow System, Light, and Dark modes render correctly.
- [ ] 1024×600 layout remains usable.
- [ ] 200% text scaling remains usable without clipped critical controls.
- [ ] Keyboard-only navigation and documented shortcuts work with visible focus.
- [ ] GNOME High Contrast keeps text and controls legible.
- [ ] Orca exposes meaningful names/roles for primary controls and status changes.
- [ ] Footer legal text remains legible and non-dominant.
- [ ] Only one valid primary action is visually emphasized at a time.

## Legal and publisher checks

- [ ] `LICENSE`, `LICENSES/`, `docs/LICENSING.md`, and third-party notices are reviewed.
- [ ] REUSE 3.3 passes on the exact release tree.
- [ ] Release-owner rights/provenance attestation is recorded against the exact tag
      and artifact hashes.
- [ ] GitHub Private Vulnerability Reporting is enabled.
- [ ] `git config --show-origin --get user.email` is reviewed; use the GitHub-provided
      noreply address if the publisher email should remain private.
- [ ] No unapproved personal/contact email is embedded in the release tree.
- [ ] Dependency/model licenses and current security advisories are reviewed on the
      publication date.

## Publication

- [ ] No source or artifact is rebuilt after final qualification.
- [ ] Push the exact tested source tree to `main`.
- [ ] Create annotated tag `v1.0.0` on that exact commit.
- [ ] Upload the exact tested ZIP, tar.gz, and SHA-256 checksum file.
- [ ] Publish concise release notes based on `docs/CHANGELOG.md`.
