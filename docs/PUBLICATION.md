<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Publication Policy

VerseLatch 1.0.0 is the first stable public release. Publish only the exact frozen
artifacts that pass both the target-Arch native gate and manual acceptance.

## Canonical endpoints

- Source: `https://github.com/erhansavas/verselatch`
- Issues: `https://github.com/erhansavas/verselatch/issues`
- Application ID: `io.github.erhansavas.verselatch`

## Release procedure

1. Freeze the final source tree and generate deterministic ZIP/tar.gz artifacts.
2. Run `./tools/public_release_check.sh` on the frozen tree.
3. Run `./tools/native_release_check.sh` on the exact final ZIP on the supported
   Arch host.
4. Complete the manual real-audio, save/cancel, non-ASCII, 200% scaling,
   keyboard-only, High Contrast, and Orca checks on those same installed bytes.
5. Confirm repository security settings and publisher Git identity/privacy.
6. Push the tested source tree, tag `v1.0.0`, and upload the exact tested artifacts
   plus their SHA-256 values. Do not rebuild after qualification.

## Distribution scope

The initial publication target is GitHub. AUR packaging is a separate follow-up
after the GitHub release is stable and its clean-package build is revalidated.

Flathub is not a 1.0.0 publication target under the policy reviewed on 2026-08-12:
Flathub currently disallows applications containing AI-generated or AI-assisted
code/documentation except where an explicit exception is granted. Any future
Flathub work requires a fresh policy and sandbox review rather than reusing this
release decision.

## Immutability

Once `v1.0.0` is published, do not replace its source or release assets with changed
bytes under the same version. Fixes are released as a new version.
