<!-- SPDX-FileCopyrightText: 2026 erhansavas -->
<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Pre-publication rename: LyricFix to VerseLatch

`LyricFix` was a private pre-publication codename. The public release name is `VerseLatch`, with application ID `io.github.erhansavas.verselatch` and command `verselatch`.

No public compatibility promise is made for the old codename because no public release was made under it.

## Existing local test installation

VerseLatch uses separate XDG paths and does not overwrite the old LyricFix application, settings, logs, cache, or model. The model installer may **copy** an existing LyricFix Large v3 Turbo model only after verifying the exact pinned byte size and SHA-256. It never symlinks, hard-links, moves, edits, or deletes the old model.

Test VerseLatch first. Remove the older LyricFix test installation only after you are satisfied with the renamed candidate. LRC files next to user audio are never migration targets.
