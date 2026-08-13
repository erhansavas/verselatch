# SPDX-FileCopyrightText: 2026 erhansavas
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

from verselatch_app.files import LyricsDocument, SaveReceipt, SaveRequest
from verselatch_core.constants import MAX_AUDIO_BYTES, MAX_LYRICS_BYTES
from verselatch_core.storage import (
    require_regular_file_state,
    safe_read_text,
    safe_write_reviewed_lrc,
)

from .linux_source import (
    identify_linux_source,
    revalidate_linux_source,
    source_path,
    source_revision,
)


class LinuxFileService:
    """Linux adapter for bounded reads, source identity, and atomic reviewed saves."""

    def revalidate(self, source) -> bool:
        return revalidate_linux_source(source)

    def read_lyrics(self, source) -> LyricsDocument:
        path = source_path(source)
        revision = source_revision(source)
        require_regular_file_state(
            path,
            revision,
            description="Lyrics source",
            maximum_bytes=MAX_LYRICS_BYTES,
        )
        text = safe_read_text(path)
        require_regular_file_state(
            path,
            revision,
            description="Lyrics source",
            maximum_bytes=MAX_LYRICS_BYTES,
        )
        return LyricsDocument(source=source, text=text)

    def save_reviewed_lrc(self, request: SaveRequest) -> SaveReceipt:
        audio_path = source_path(request.audio)
        lyrics_path = source_path(request.lyrics) if request.lyrics is not None else None
        lyrics_state = source_revision(request.lyrics) if request.lyrics is not None else None
        output, backup = safe_write_reviewed_lrc(
            content=request.content,
            current_audio_path=audio_path,
            analyzed_audio_path=audio_path,
            analyzed_audio_state=source_revision(request.audio),
            current_lyrics_path=lyrics_path,
            analyzed_lyrics_path=lyrics_path,
            analyzed_lyrics_state=lyrics_state,
            maximum_audio_bytes=MAX_AUDIO_BYTES,
            maximum_lyrics_bytes=MAX_LYRICS_BYTES,
        )
        return SaveReceipt(
            output=identify_linux_source(output, maximum_bytes=MAX_LYRICS_BYTES),
            backup=(
                identify_linux_source(backup, maximum_bytes=MAX_LYRICS_BYTES)
                if backup is not None
                else None
            ),
        )
