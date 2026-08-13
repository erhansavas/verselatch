<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Publication Policy

VerseLatch 1.0.0 is the immutable first stable public release. Its existing tag and
release assets are historical and must not be moved, replaced, regenerated, or
silently patched. Corrective work is prepared as VerseLatch 1.0.1.

## Canonical endpoints

- Source: `https://github.com/erhansavas/verselatch`
- Issues: `https://github.com/erhansavas/verselatch/issues`
- Application ID: `io.github.erhansavas.verselatch`

## 1.0.1 release procedure

1. Freeze the final 1.0.1 source tree and generate deterministic ZIP/tar.gz artifacts.
2. Run `./tools/public_release_check.sh` on the frozen tree.
3. Run `./tools/native_release_check.sh` on the exact final ZIP on the supported Arch host.
4. Complete the manual real-audio, stale-source, install/upgrade/uninstall, save/cancel,
   non-ASCII, 200% scaling, keyboard-only, High Contrast, and Orca checks on those same bytes.
5. Confirm repository security settings and publisher Git identity/privacy.
6. Push only after qualification, create a new annotated `v1.0.1` tag, and upload the exact
   tested artifacts plus their SHA-256 values. Do not rebuild after qualification.

## Distribution scope

GitHub remains the release target for this corrective cycle. AUR work is separate and must
not be mixed into 1.0.1 qualification.

Flathub was not a 1.0.0 publication target under the policy reviewed on 2026-08-12. Any
future Flathub work requires a fresh policy and sandbox review rather than reusing that
decision.

## Immutability

`v1.0.0` and its uploaded assets remain unchanged. Once `v1.0.1` is published, the same
rule applies to that tag and its assets; later corrections require another version.
