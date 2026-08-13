# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from pathlib import Path

from verselatch_app.session import SourceIdentity
from verselatch_core.errors import VerseLatchError
from verselatch_core.storage import regular_file_state, require_regular_file_state


FileRevision = tuple[int, int, int, int, int]


def source_path(source: SourceIdentity) -> Path:
    path = Path(source.location)
    if not path.is_absolute():
        raise VerseLatchError("Linux source location must be an absolute path.")
    return path


def source_revision(source: SourceIdentity) -> FileRevision:
    value = source.revision
    if not isinstance(value, tuple) or len(value) != 5:
        raise VerseLatchError("Linux source revision is invalid.")
    if any(not isinstance(item, int) or isinstance(item, bool) for item in value):
        raise VerseLatchError("Linux source revision is invalid.")
    return value


def identify_linux_source(path: str | Path, *, maximum_bytes: int | None = None) -> SourceIdentity:
    candidate = Path(path).expanduser().resolve(strict=True)
    state = regular_file_state(
        candidate,
        description="Selected source",
        maximum_bytes=maximum_bytes,
    )
    return SourceIdentity(str(candidate), state)


def revalidate_linux_source(source: SourceIdentity) -> bool:
    try:
        require_regular_file_state(
            source_path(source),
            source_revision(source),
            description="Selected source",
        )
    except (OSError, VerseLatchError):
        return False
    return True
