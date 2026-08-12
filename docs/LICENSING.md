<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Licensing

VerseLatch first-party source, scripts, project documentation, and original
project artwork in the 1.0.0 release source are offered under the **GNU General
Public License version 3 only** (`GPL-3.0-only`), except where a file carries a
different explicit SPDX license identifier. The complete, unmodified GPLv3
text is in `../LICENSES/GPL-3.0-only.txt`. Source/script files carry SPDX
identifiers and `../REUSE.toml` covers the remaining files that cannot reliably
carry inline notices.

## Why GPL-3.0-only

`GPL-3.0-only` makes the exact grant explicit: GPL version 3, without
automatically granting recipients the option to choose a future GPL version.
That is a narrower and more predictable version choice than `-or-later`, at
the cost of less future compatibility flexibility. This choice does **not**
change the terms already attached to copies distributed earlier under another
valid grant, and it does not permit VerseLatch to relabel material owned by
another rightsholder.

VerseLatch 1.0.0 therefore uses `GPL-3.0-only` as the current first-party
license while retaining a manual publication gate in `PROVENANCE.md`: a public
distributor must still establish that the listed rightsholder has the authority
to license every first-party item under those terms. External contributions,
if any, retain their actual recorded copyright/license status.

## Distribution

When VerseLatch source is distributed, preserve the applicable notices and
provide recipients with the GPLv3 license text. If object-code distribution is
added later, follow GPLv3 section 6 for corresponding source. Do not impose
additional restrictions that conflict with recipients' GPL rights.

## User content

The project license does not automatically license a user's audio, lyrics, LRC
files, or other content. VerseLatch grants no rights to third-party songs,
recordings, or lyrics; users remain responsible for rights applicable to the
content they process or distribute.

## Third-party components

VerseLatch does not intentionally vendor the Whisper model, whisper.cpp, aubio,
GTK, libadwaita, PyGObject, or a custom font into the source archive. They are
separately obtained/system-provided and keep their own licenses, recorded in
`DEPENDENCIES.md` and `THIRD_PARTY_NOTICES.txt`.

The AppStream MetaInfo file `../data/io.github.erhansavas.verselatch.metainfo.xml`
is separately marked MIT so the metadata itself is permissively reusable. This
does not change the application's `GPL-3.0-only` project license. The MIT text
is in `../LICENSES/MIT.txt`.

## Asset policy

The VerseLatch application and symbolic icons are first-party project artwork.
UI action icons use names from the installed desktop icon theme rather than
copied third-party SVG files. No custom interface font is bundled.
