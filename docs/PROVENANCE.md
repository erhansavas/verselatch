<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Provenance policy

The release tree records first-party material as:

<!-- REUSE-IgnoreStart -->
```text
SPDX-FileCopyrightText: 2026 erhansavas
SPDX-License-Identifier: GPL-3.0-only
```
<!-- REUSE-IgnoreEnd -->

The AppStream MetaInfo file is separately marked MIT so the metadata itself
can be reused independently; that separate file license does not alter the
application's project license. Third-party dependencies/model material
retain their upstream licenses and are not silently relabeled as VerseLatch
first-party work.

## Inclusion rule

Do not add copied code, icons, fonts, screenshots, audio, lyrics, datasets,
model weights or other copyrighted material unless its origin, rightsholder
where applicable and compatible license are recorded. Unclear provenance is a
reason not to include the material.

The application icon and symbolic icon in `data/` are first-party VerseLatch
artwork based on the project's lyric-line + timing-latch metaphor. No external
SVG path data or third-party icon-pack asset is required for the application
identity.

## Release-owner attestation

This is intentionally a **manual publication gate**. Metadata and automated
tests cannot prove copyright ownership or the absence of third-party claims.

Before a public release, the release owner must factually confirm all of the
following against the exact frozen commit/tag and artifact hashes:

- first-party VerseLatch source, scripts, documentation and original artwork
  are authored by the listed rightsholder or have separately recorded
  provenance and permission;
- no unresolved employer, school, client or other third-party ownership claim
  applies to the first-party release material;
- no non-trivial third-party code/artwork/font/audio/lyric/dataset/model material
  is included without recorded origin and compatible terms;
- any external contributions retain correct authorship and were submitted under
  terms compatible with the affected file/project license;
- AI-assisted material was manually reviewed for unexpected copying,
  provenance/licensing inconsistency and security-sensitive behavior.

The attestation is recorded in the immutable public tag/release record (or an
external signed release record), not by editing the already-tested source tree.
It should state the reviewed commit/tag, review date, exact ZIP/tarball hashes,
and the release owner's confirmation. This keeps the byte-for-byte QA evidence
valid while preserving a factual human provenance decision.

## Contribution provenance

Contributors must have the right to submit their material and permit it to be
distributed under the license declared for the affected file, normally
GPL-3.0-only. Contributions with unclear provenance are not accepted.

This document is an engineering provenance record, not a legal opinion or a
promise of zero legal risk.
